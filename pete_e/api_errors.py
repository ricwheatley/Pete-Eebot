"""Shared API error envelope and correlation ID support."""

from __future__ import annotations

from dataclasses import dataclass
import re
import uuid
from typing import Any

try:  # pragma: no cover - exercised when FastAPI is installed.
    from fastapi import HTTPException, Request
except ImportError:  # pragma: no cover - test stubs cover this path.
    HTTPException = Exception  # type: ignore[assignment]
    Request = Any  # type: ignore[assignment]

try:  # pragma: no cover - exercised when FastAPI is installed.
    from fastapi.exceptions import RequestValidationError
except ImportError:  # pragma: no cover - FastAPI stubs do not expose this.
    RequestValidationError = None  # type: ignore[assignment]

try:  # pragma: no cover - exercised when FastAPI is installed.
    from fastapi.responses import JSONResponse
except ImportError:  # pragma: no cover - fallback for the repo's API stubs.

    class JSONResponse:  # type: ignore[no-redef]
        def __init__(self, content: dict[str, Any], status_code: int = 200, headers: dict[str, str] | None = None):
            self.content = content
            self.status_code = status_code
            self.headers = headers or {}

from pete_e.application.exceptions import ApplicationError

CORRELATION_ID_HEADER = "X-Correlation-ID"
REQUEST_ID_HEADER = "X-Request-ID"
_CORRELATION_ID_RE = re.compile(r"^[A-Za-z0-9_.:/@-]{1,128}$")


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
    return JSONResponse(
        status_code=status_code,
        headers=response_headers,
        content=ApiError(
            code=code,
            message=message,
            details=details,
            correlation_id=correlation_id,
        ).to_payload(),
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
        details={"errors": errors} if errors is not None else None,
    )


async def unhandled_exception_handler(request: Request, exc: Exception):  # noqa: ARG001
    return build_error_response(
        request,
        status_code=500,
        code="internal_server_error",
        message="Internal server error",
    )


def install_api_error_handlers(api_app: Any) -> None:
    """Install error handlers and correlation middleware when real FastAPI is available."""

    middleware = getattr(api_app, "middleware", None)
    if callable(middleware):
        middleware("http")(correlation_id_middleware)

    add_handler = getattr(api_app, "add_exception_handler", None)
    if not callable(add_handler):
        return

    add_handler(HTTPException, http_exception_handler)
    add_handler(ApplicationError, application_error_handler)
    if RequestValidationError is not None:
        add_handler(RequestValidationError, validation_exception_handler)
    add_handler(Exception, unhandled_exception_handler)


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
