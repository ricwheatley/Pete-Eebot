"""HTTP security middleware and CORS configuration."""

from __future__ import annotations

from typing import Any

from pete_e.config import get_env
from starlette.middleware.cors import CORSMiddleware

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def configured_cors_origins() -> list[str]:
    raw = str(get_env("PETEEEBOT_CORS_ALLOWED_ORIGINS", "") or "")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _hsts_enabled() -> bool:
    configured = get_env("PETEEEBOT_ENABLE_HSTS", None)
    if configured is not None:
        return bool(configured)
    environment = str(get_env("ENVIRONMENT", "development") or "development").strip().lower()
    return environment not in {"dev", "development", "local", "test", "testing"}


async def security_headers_middleware(request, call_next):
    response = await call_next(request)
    for header, value in SECURITY_HEADERS.items():
        if header not in response.headers:
            response.headers[header] = value
    if _hsts_enabled():
        if "Strict-Transport-Security" not in response.headers:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def install_security_middleware(api_app: Any) -> None:
    origins = configured_cors_origins()
    if origins:
        api_app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
            allow_headers=[
                "Content-Type",
                "X-CSRF-Token",
                "X-Correlation-ID",
                "X-Request-ID",
            ],
            expose_headers=["X-Correlation-ID", "X-Request-ID"],
            max_age=600,
        )

    api_app.middleware("http")(security_headers_middleware)


__all__ = [
    "SECURITY_HEADERS",
    "configured_cors_origins",
    "install_security_middleware",
    "security_headers_middleware",
]
