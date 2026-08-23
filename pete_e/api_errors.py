"""Shared API error envelope and correlation ID support."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum
import math
import re
import uuid
from typing import Any

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from pete_e.application.exceptions import ApplicationError

CORRELATION_ID_HEADER = "X-Correlation-ID"
REQUEST_ID_HEADER = "X-Request-ID"
_CORRELATION_ID_RE = re.compile(r"^[A-Za-z0-9_.:/@-]{1,128}$")
_REDACTED = "[REDACTED]"
_NON_SERIALIZABLE = "[NON-SERIALIZABLE VALUE OMITTED]"
_SENSITIVE_DETAIL_KEYS = {
    "api_key",
    "authorization",
    "body",
    "cookie",
    "cookies",
    "credential",
    "credentials",
    "headers",
    "mfa",
    "mfa_code",
    "passwd",
    "password",
    "recovery_code",
    "refresh_token",
    "secret",
    "session",
    "session_token",
    "set_cookie",
    "token",
    "totp_code",
}


def _normalized_detail_key(value: Any) -> str:
    if isinstance(value, (str, int, float, bool)):
        return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    return type(value).__name__


def _json_detail_key(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return type(value).__name__


def _is_sensitive_detail_key(value: Any) -> bool:
    normalized = _normalized_detail_key(value)
    if normalized in _SENSITIVE_DETAIL_KEYS:
        return True
    return any(
        normalized.endswith(f"_{suffix}")
        for suffix in (
            "api_key",
            "body",
            "cookie",
            "credential",
            "mfa",
            "password",
            "secret",
            "session",
            "token",
        )
    )


def _json_safe_error_value(
    value: Any,
    *,
    field_name: Any = None,
    ancestors: set[int] | None = None,
    depth: int = 0,
) -> Any:
    """Return bounded JSON-native diagnostics while omitting request inputs and secrets."""

    normalized_field = (
        _normalized_detail_key(field_name) if field_name is not None else ""
    )
    if normalized_field in {"ctx", "input"} or _is_sensitive_detail_key(field_name):
        return _REDACTED
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _NON_SERIALIZABLE
    if isinstance(value, (bytes, bytearray, memoryview)):
        return _REDACTED
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Enum):
        return _json_safe_error_value(value.value, ancestors=ancestors, depth=depth + 1)
    if depth >= 12:
        return _NON_SERIALIZABLE

    ancestors = ancestors or set()
    identity = id(value)
    if identity in ancestors:
        return _NON_SERIALIZABLE

    if isinstance(value, Mapping):
        next_ancestors = {*ancestors, identity}
        return {
            _json_detail_key(key): _json_safe_error_value(
                item,
                field_name=key,
                ancestors=next_ancestors,
                depth=depth + 1,
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        next_ancestors = {*ancestors, identity}
        return [
            _json_safe_error_value(
                item,
                ancestors=next_ancestors,
                depth=depth + 1,
            )
            for item in value
        ]
    return _NON_SERIALIZABLE


def _safe_validation_errors(errors: Any) -> Any:
    if not isinstance(errors, (list, tuple)):
        return errors

    sanitized = []
    for error in errors:
        if not isinstance(error, Mapping):
            sanitized.append(error)
            continue
        item = dict(error)
        location = item.get("loc")
        error_type = str(item.get("type") or "")
        if (
            "ctx" in item
            or (
                isinstance(location, (list, tuple))
                and any(_is_sensitive_detail_key(part) for part in location)
            )
        ) or error_type.startswith(("assertion_error", "value_error")):
            item["msg"] = "Invalid value"
        sanitized.append(item)
    return sanitized


@dataclass(frozen=True)
class ApiError:
    code: str
    message: str
    correlation_id: str
    details: dict[str, Any] | list[Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "correlation_id": self.correlation_id,
        }
        if self.details is not None:
            body["details"] = self.details
        return {"error": body}


def normalize_correlation_id(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    if not _CORRELATION_ID_RE.fullmatch(candidate):
        return None
    return candidate


def new_correlation_id() -> str:
    return str(uuid.uuid4())


def get_or_create_correlation_id(request: Request) -> str:
    state = getattr(request, "state", None)
    existing = normalize_correlation_id(getattr(state, "correlation_id", None))
    if existing:
        return existing

    headers = getattr(request, "headers", {}) or {}
    requested = normalize_correlation_id(headers.get(CORRELATION_ID_HEADER) or headers.get(REQUEST_ID_HEADER))
    correlation_id = requested or new_correlation_id()
    if state is not None:
        setattr(state, "correlation_id", correlation_id)
    return correlation_id


def correlation_headers(correlation_id: str) -> dict[str, str]:
    return {
        CORRELATION_ID_HEADER: correlation_id,
        REQUEST_ID_HEADER: correlation_id,
    }


def status_code_to_error_code(status_code: int) -> str:
    return {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
        429: "rate_limited",
        500: "internal_server_error",
        503: "service_unavailable",
        504: "timeout",
    }.get(status_code, "http_error")


def _coerce_http_detail(status_code: int, detail: Any) -> tuple[str, str, dict[str, Any] | list[Any] | None]:
    code = status_code_to_error_code(status_code)
    message = "Request failed"
    details = None

    if isinstance(detail, dict):
        code = str(detail.get("code") or code)
        message = str(detail.get("message") or detail.get("error") or message)
        details = {key: value for key, value in detail.items() if key not in {"code", "message", "error"}}
        if not details:
            details = None
    elif isinstance(detail, list):
        message = "Request validation failed" if status_code == 422 else message
        details = detail
    elif detail:
        message = str(detail)
    elif status_code == 401:
        message = "Unauthorized"
    elif status_code == 404:
        message = "Resource not found"

    return code, message, details


def build_error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | list[Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    correlation_id = get_or_create_correlation_id(request)
    response_headers = dict(headers or {})
    response_headers.update(correlation_headers(correlation_id))
    content = ApiError(
        code=code,
        message=message,
        details=details,
        correlation_id=correlation_id,
    ).to_payload()
    return JSONResponse(
        status_code=status_code,
        headers=response_headers,
        content=_json_safe_error_value(content),
    )


async def correlation_id_middleware(request: Request, call_next):
    correlation_id = get_or_create_correlation_id(request)
    response = await call_next(request)
    for header, value in correlation_headers(correlation_id).items():
        response.headers[header] = value
    return response


async def http_exception_handler(request: Request, exc: HTTPException):
    status_code = getattr(exc, "status_code", 500)
    detail = getattr(exc, "detail", None)
    code, message, details = _coerce_http_detail(status_code, detail)
    return build_error_response(
        request,
        status_code=status_code,
        code=code,
        message=message,
        details=details,
        headers=getattr(exc, "headers", None),
    )


async def application_error_handler(request: Request, exc: ApplicationError):
    return build_error_response(
        request,
        status_code=exc.http_status,
        code=exc.code,
        message=exc.message,
    )


async def validation_exception_handler(request: Request, exc: Exception):
    errors = exc.errors() if hasattr(exc, "errors") else None
    return build_error_response(
        request,
        status_code=422,
        code="validation_error",
        message="Request validation failed",
        details={"errors": _safe_validation_errors(errors)}
        if errors is not None
        else None,
    )


async def unhandled_exception_handler(request: Request, exc: Exception):  # noqa: ARG001
    return build_error_response(
        request,
        status_code=500,
        code="internal_server_error",
        message="Internal server error",
    )


def install_api_error_handlers(api_app: Any) -> None:
    """Install error handlers and correlation middleware on a FastAPI app."""

    api_app.middleware("http")(correlation_id_middleware)
    api_app.add_exception_handler(HTTPException, http_exception_handler)
    api_app.add_exception_handler(ApplicationError, application_error_handler)
    api_app.add_exception_handler(RequestValidationError, validation_exception_handler)
    api_app.add_exception_handler(Exception, unhandled_exception_handler)


__all__ = [
    "ApiError",
    "CORRELATION_ID_HEADER",
    "REQUEST_ID_HEADER",
    "application_error_handler",
    "build_error_response",
    "correlation_headers",
    "correlation_id_middleware",
    "get_or_create_correlation_id",
    "http_exception_handler",
    "install_api_error_handlers",
    "new_correlation_id",
    "normalize_correlation_id",
    "status_code_to_error_code",
    "unhandled_exception_handler",
    "validation_exception_handler",
]
