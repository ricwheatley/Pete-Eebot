from fastapi import FastAPI, Header, HTTPException, Query, Request

from pete_e.api_routes import (
    auth_router,
    logs_webhooks_router,
    metrics_router,
    nutrition_router,
    plan_router,
    root_router,
    status_sync_router,
)
from pete_e.api_routes.dependencies import (
    DEFAULT_SYNC_TIMEOUT_SECONDS,
    enforce_command_rate_limit,
    get_status_service,
    run_guarded_high_risk_operation,
    validate_api_key,
)
from pete_e.api_errors import install_api_error_handlers
from pete_e.api_security import install_security_middleware
from pete_e.api_routes.logs_webhooks import github_webhook, logs
from pete_e.application.sync import run_sync_with_retries
from pete_e.config import settings as _settings
from pete_e.cli.status import DEFAULT_TIMEOUT_SECONDS, render_results
from pete_e.domain.auth import ROLE_OPERATOR

settings = _settings  # Backward-compatible module export for tests/consumers.
API_V1_PREFIX = "/api/v1"
LEGACY_ROUTE_DEPRECATION_NOTE = (
    "Unversioned API routes remain available for transition only. "
    "New UI and machine clients should use /api/v1."
)

ROUTERS = (
    auth_router,
    root_router,
    metrics_router,
    nutrition_router,
    plan_router,
    status_sync_router,
    logs_webhooks_router,
)

__all__ = [
    "API_V1_PREFIX",
    "LEGACY_ROUTE_DEPRECATION_NOTE",
    "ROUTERS",
    "app",
    "auth_router",
    "github_webhook",
    "include_api_routers",
    "logs",
    "settings",
    "status",
    "sync",
]

app = FastAPI(title="Pete-Eebot API")
install_security_middleware(app)
install_api_error_handlers(app)


def include_api_routers(api_app: FastAPI) -> None:
    """Mount both legacy and versioned API routes during the transition."""

    for router in ROUTERS:
        api_app.include_router(router)
    for router in ROUTERS:
        api_app.include_router(router, prefix=API_V1_PREFIX)


if hasattr(app, "include_router"):
    include_api_routers(app)


def status(
    request: Request,
    x_api_key: str = Header(None),
    timeout: float = Query(DEFAULT_TIMEOUT_SECONDS, ge=0.1),
):
    validate_api_key(request, x_api_key)
    try:
        results = get_status_service().run_checks(timeout=timeout)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    checks = [{"name": r.name, "ok": r.ok, "detail": r.detail} for r in results]
    return {"ok": all(result["ok"] for result in checks), "checks": checks, "summary": render_results(results)}


def sync(
    request: Request,
    x_api_key: str = Header(None),
    days: int = Query(7, ge=1),
    retries: int = Query(3, ge=0),
    timeout: float = Query(DEFAULT_SYNC_TIMEOUT_SECONDS, ge=1, le=900),
):
    validate_api_key(request, x_api_key, required_session_role=ROLE_OPERATOR)
    enforce_command_rate_limit(request, "sync")
    try:
        result = run_guarded_high_risk_operation(
            "sync",
            lambda: run_sync_with_retries(days=days, retries=retries),
            timeout_seconds=timeout,
        )
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "success": result.success,
        "attempts": result.attempts,
        "failed_sources": result.failed_sources,
        "source_statuses": result.source_statuses,
        "undelivered_alerts": result.undelivered_alerts,
        "label": result.label,
        "summary": result.summary_line(days=days),
    }
