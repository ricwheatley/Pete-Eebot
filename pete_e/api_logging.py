"""Structured request logging for FastAPI routes."""

from __future__ import annotations

import hashlib
import time
from typing import Any

from pete_e.api_errors import get_or_create_correlation_id
from pete_e.domain.auth import AuthUser
from pete_e.infrastructure import log_utils
from pete_e.logging_setup import bind_log_context, reset_log_context


def session_fingerprint(token: str | None) -> str | None:
    """Return a non-secret stable identifier for a browser session token."""

    if not token:
        return None
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def _request_path(request: Any) -> str:
    scope = getattr(request, "scope", None)
    if isinstance(scope, dict) and scope.get("path"):
        return str(scope["path"])
    url = getattr(request, "url", None)
    return str(getattr(url, "path", None) or getattr(request, "path", "/"))


def _request_method(request: Any) -> str:
    return str(getattr(request, "method", "GET") or "GET").upper()


def _client_ip(request: Any) -> str | None:
    headers = getattr(request, "headers", {}) or {}
    forwarded_for = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For")
    if forwarded_for:
        return str(forwarded_for).split(",", 1)[0].strip()
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    return str(host) if host else None


def _session_token(request: Any) -> str | None:
    cookies = getattr(request, "cookies", None)
    if isinstance(cookies, dict):
        for name, value in cookies.items():
            if "session" in str(name).lower() and value:
                return str(value)

    headers = getattr(request, "headers", {}) or {}
    raw_cookie = headers.get("cookie") or headers.get("Cookie") or ""
    for part in str(raw_cookie).split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and "session" in name.lower() and value:
            return value
    return None


def identity_fields_from_request(request: Any) -> dict[str, Any]:
    """Extract safe identity fields that may be known for this request."""

    state = getattr(request, "state", None)
    user = getattr(state, "auth_user", None)
    fields: dict[str, Any] = {
        "auth_scheme": getattr(state, "auth_scheme", None),
        "session_id": session_fingerprint(_session_token(request)),
    }
    if isinstance(user, AuthUser):
        fields.update(
            {
                "user_id": user.id,
                "username": user.username,
                "roles": list(user.roles),
            }
        )
    return {key: value for key, value in fields.items() if value is not None}


def install_request_logging_middleware(api_app: Any) -> None:
    middleware = getattr(api_app, "middleware", None)
    if callable(middleware):
        middleware("http")(request_logging_middleware)


async def request_logging_middleware(request: Any, call_next):
    request_id = get_or_create_correlation_id(request)
    method = _request_method(request)
    path = _request_path(request)
    client_ip = _client_ip(request)
    token = bind_log_context(
        request_id=request_id,
        correlation_id=request_id,
        http_method=method,
        http_path=path,
        client_ip=client_ip,
        component="api",
    )
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = int(getattr(response, "status_code", 200) or 200)
        return response
    except Exception:
        status_code = 500
        raise
    finally:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        outcome = "succeeded" if status_code < 400 else "failed"
        log_utils.log_event(
            event="http_request",
            message=f"{method} {path} {status_code}",
            tag="API",
            level="INFO" if status_code < 500 else "ERROR",
            outcome=outcome,
            request_id=request_id,
            correlation_id=request_id,
            http_method=method,
            http_path=path,
            http_status=status_code,
            duration_ms=duration_ms,
            client_ip=client_ip,
            **identity_fields_from_request(request),
        )
        reset_log_context(token)


__all__ = [
    "identity_fields_from_request",
    "install_request_logging_middleware",
    "request_logging_middleware",
    "session_fingerprint",
]
