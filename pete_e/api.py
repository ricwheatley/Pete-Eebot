from fastapi import FastAPI, Header, HTTPException, Query, Request

from pete_e.api_routes import (
    logs_webhooks_router,
    metrics_router,
    plan_router,
    root_router,
    status_sync_router,
)
from pete_e.api_routes.dependencies import get_status_service, validate_api_key
from pete_e.application.sync import run_sync_with_retries
from pete_e.cli.status import DEFAULT_TIMEOUT_SECONDS, render_results

app = FastAPI(title="Pete-Eebot API")

app.include_router(root_router)
app.include_router(metrics_router)
app.include_router(plan_router)
app.include_router(status_sync_router)
app.include_router(logs_webhooks_router)


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
):
    validate_api_key(request, x_api_key)
    try:
        result = run_sync_with_retries(days=days, retries=retries)
    except Exception as exc:
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
