from __future__ import annotations

from typing import Any

import fastapi
from fastapi import HTTPException, Request

from pete_e.api_routes.dependencies import (
    clear_session_cookies,
    csrf_header_name,
    enforce_csrf_for_session,
    enforce_login_attempt_allowed,
    generate_csrf_token,
    get_user_service,
    record_login_failure,
    record_login_success,
    require_browser_user,
    session_token_from_request,
    set_session_cookies,
)

Response = getattr(fastapi, "Response", object)
router = fastapi.APIRouter() if hasattr(fastapi, "APIRouter") else fastapi.FastAPI()


def _client_ip(request: Request) -> str | None:
    headers = getattr(request, "headers", {}) or {}
    forwarded_for = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    return str(host) if host else None


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


@router.post("/auth/login")
def login(request: Request, response: Response, payload: dict[str, Any] | None = None):
    payload = payload or {}
    login_value = payload.get("login") or payload.get("username") or payload.get("email")
    password = payload.get("password")
    if not login_value or not password:
        raise HTTPException(status_code=400, detail="login and password are required")

    enforce_login_attempt_allowed(request, str(login_value))
    user = get_user_service().authenticate_user(str(login_value), str(password))
    if user is None:
        record_login_failure(request, str(login_value))
        raise HTTPException(status_code=401, detail="Invalid login or password")

    record_login_success(request, str(login_value))
    created = get_user_service().create_session(
        user,
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
    )
    csrf_token = generate_csrf_token(created.token)
    set_session_cookies(response, created.token, csrf_token)

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
    return {"authenticated": False}


@router.get("/auth/session")
def session(request: Request):
    user = require_browser_user(request)
    return {"authenticated": True, "user": _user_payload(user)}
