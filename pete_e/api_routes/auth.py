from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import parse_qsl

import fastapi
from fastapi import HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError

from pete_e.api_routes.dependencies import (
    clear_session_cookies,
    csrf_header_name,
    enforce_csrf_for_session,
    enforce_login_attempt_allowed,
    generate_csrf_token,
    get_user_service,
    mark_authenticated_request,
    record_login_failure,
    record_login_success,
    require_browser_user,
    session_token_from_request,
    set_session_cookies,
)
from pete_e.api_errors import get_or_create_correlation_id
from pete_e.api_logging import session_fingerprint
from pete_e.client_identity import client_identity
from pete_e.infrastructure import log_utils
from pete_e.domain.auth import AuthenticatedPrincipal

router = fastapi.APIRouter()

_LOGIN_REQUEST_BODY = {
    "required": True,
    "content": {
        media_type: {
            "schema": {
                "type": "object",
                "required": ["login", "password"],
                "properties": {
                    "login": {"type": "string"},
                    "password": {"type": "string", "format": "password"},
                    "mfa_code": {"type": "string"},
                },
            }
        }
        for media_type in ("application/json", "application/x-www-form-urlencoded")
    },
}


def _request_validation_error(error_type: str, message: str) -> RequestValidationError:
    return RequestValidationError(
        [
            {
                "type": error_type,
                "loc": ("body",),
                "msg": message,
            }
        ]
    )


async def _login_payload(request: Request) -> dict[str, Any]:
    """Parse only the two evidenced login media types without retaining raw credentials."""

    content_type = str(request.headers.get("content-type") or "")
    media_type = content_type.partition(";")[0].strip().lower()

    if media_type == "application/x-www-form-urlencoded":
        try:
            encoded = (await request.body()).decode("utf-8", errors="strict")
            return dict(
                parse_qsl(
                    encoded,
                    keep_blank_values=True,
                    strict_parsing=True,
                    encoding="utf-8",
                    errors="strict",
                    max_num_fields=20,
                )
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise _request_validation_error(
                "form_parsing",
                "Input should be valid URL-encoded form data",
            ) from exc

    if media_type == "application/json" or media_type.endswith("+json"):
        try:
            payload = await request.json()
        except (UnicodeDecodeError, ValueError) as exc:
            raise _request_validation_error(
                "json_invalid", "Invalid JSON body"
            ) from exc
        if payload is None:
            return {}
        if not isinstance(payload, dict):
            raise _request_validation_error(
                "dict_type", "Input should be a valid dictionary"
            )
        return payload

    if not media_type and not await request.body():
        return {}

    raise HTTPException(
        status_code=415,
        detail={
            "code": "unsupported_media_type",
            "message": (
                "Login requests require application/json or "
                "application/x-www-form-urlencoded"
            ),
        },
    )


def _user_agent(request: Request) -> str | None:
    headers = getattr(request, "headers", {}) or {}
    value = headers.get("user-agent") or headers.get("User-Agent")
    return str(value) if value else None


def _user_payload(user) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "display_name": user.display_name,
        "roles": list(user.roles),
    }


@router.post("/auth/login", openapi_extra={"requestBody": _LOGIN_REQUEST_BODY})
def login(
    request: Request,
    response: Response,
    payload: Annotated[dict[str, Any], fastapi.Depends(_login_payload)],
):
    payload = payload or {}
    login_value = payload.get("login") or payload.get("username") or payload.get("email")
    password = payload.get("password")
    if not login_value or not password:
        raise HTTPException(status_code=400, detail="login and password are required")

    enforce_login_attempt_allowed(request, str(login_value))
    user = get_user_service().authenticate_user(str(login_value), str(password))
    if user is None:
        record_login_failure(request, str(login_value))
        log_utils.log_event(
            event="auth_login",
            message="login failed",
            tag="AUTH",
            level="WARNING",
            outcome="failed",
            request_id=get_or_create_correlation_id(request),
            client_ip=client_identity(request),
            login=str(login_value),
        )
        raise HTTPException(status_code=401, detail="Invalid login or password")

    mfa_code = payload.get("mfa_code") or payload.get("totp_code") or payload.get("recovery_code")
    user_service = get_user_service()
    requires_mfa = getattr(user_service, "user_requires_mfa", lambda current_user: bool(getattr(current_user, "mfa_enabled", False)))
    verify_mfa = getattr(user_service, "verify_mfa_code", lambda current_user, code: True)
    if requires_mfa(user):
        if not mfa_code:
            return {
                "authenticated": False,
                "mfa_required": True,
                "csrf_header": csrf_header_name(),
            }
        if not verify_mfa(user, str(mfa_code)):
            record_login_failure(request, str(login_value))
            log_utils.log_event(
                event="auth_login",
                message="login MFA failed",
                tag="AUTH",
                level="WARNING",
                outcome="failed",
                request_id=get_or_create_correlation_id(request),
                client_ip=client_identity(request),
                login=str(login_value),
            )
            raise HTTPException(status_code=401, detail="Invalid MFA code")

    record_login_success(request, str(login_value))
    created = get_user_service().create_session(
        user,
        ip_address=client_identity(request),
        user_agent=_user_agent(request),
    )
    csrf_token = generate_csrf_token(created.token)
    set_session_cookies(response, created.token, csrf_token)
    mark_authenticated_request(request, AuthenticatedPrincipal.for_user(user))
    log_utils.log_event(
        event="auth_login",
        message="login succeeded",
        tag="AUTH",
        outcome="succeeded",
        request_id=get_or_create_correlation_id(request),
        client_ip=client_identity(request),
        user_id=user.id,
        username=user.username,
        roles=list(user.roles),
        session_id=session_fingerprint(created.token),
    )

    return {
        "authenticated": True,
        "user": _user_payload(user),
        "csrf_header": csrf_header_name(),
        "csrf_token": csrf_token,
    }


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    session_token = session_token_from_request(request)
    if not session_token:
        raise HTTPException(status_code=401, detail="Authentication required")

    require_browser_user(request)
    enforce_csrf_for_session(request, session_token)
    get_user_service().revoke_session_token(session_token)
    clear_session_cookies(response)
    log_utils.log_event(
        event="auth_logout",
        message="logout succeeded",
        tag="AUTH",
        outcome="succeeded",
        request_id=get_or_create_correlation_id(request),
        session_id=session_fingerprint(session_token),
    )
    return {"authenticated": False}


@router.get("/auth/session")
def session(request: Request):
    user = require_browser_user(request)
    return {"authenticated": True, "user": _user_payload(user)}
