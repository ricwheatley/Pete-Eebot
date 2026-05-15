import fastapi
from fastapi import Header, HTTPException, Query, Request

from pete_e.api_routes.dependencies import (
    DEFAULT_SYNC_TIMEOUT_SECONDS,
    enforce_command_rate_limit,
    get_status_service,
    run_guarded_high_risk_operation,
    validate_api_key,
)
from pete_e.application.sync import run_sync_with_retries
from pete_e.cli.status import DEFAULT_TIMEOUT_SECONDS, render_results
from pete_e.domain.auth import ROLE_OPERATOR

router = fastapi.APIRouter() if hasattr(fastapi, "APIRouter") else fastapi.FastAPI()


@router.get("/status")
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


@router.post("/sync")
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
