import fastapi
from fastapi import Header, HTTPException, Query, Request
try:
    from fastapi.responses import JSONResponse, PlainTextResponse
except ImportError:  # pragma: no cover - lightweight FastAPI stubs.

    class JSONResponse:  # type: ignore[no-redef]
        def __init__(self, content: dict, status_code: int = 200):
            self.content = content
            self.status_code = status_code
            self.body = content

    class PlainTextResponse:  # type: ignore[no-redef]
        def __init__(self, content: str, media_type: str = "text/plain"):
            self.body = content.encode("utf-8")
            self.media_type = media_type

from pete_e.api_routes.dependencies import (
    DEFAULT_SYNC_TIMEOUT_SECONDS,
    audit_command_event,
    enforce_command_rate_limit,
    get_status_service,
    prepare_job_context,
    run_guarded_high_risk_operation,
    validate_api_key,
)
from pete_e.application.sync import run_sync_with_retries
from pete_e.cli.status import DEFAULT_TIMEOUT_SECONDS, render_results
from pete_e import observability
from pete_e.domain.auth import ROLE_OPERATOR

router = fastapi.APIRouter() if hasattr(fastapi, "APIRouter") else fastapi.FastAPI()


def _checks_payload(results):
    checks = [{"name": r.name, "ok": r.ok, "detail": r.detail} for r in results]
    return {
        "ok": all(result["ok"] for result in checks),
        "checks": checks,
        "summary": render_results(results),
    }


def _json_response(payload: dict, *, status_code: int = 200):
    return JSONResponse(content=payload, status_code=status_code)


@router.get("/healthz")
def healthz():
    return {"ok": True, "status": "live"}


@router.get("/readyz")
def readyz(timeout: float = Query(DEFAULT_TIMEOUT_SECONDS, ge=0.1)):
    try:
        payload = _checks_payload(get_status_service().run_checks(timeout=timeout))
    except Exception as exc:
        payload = {
            "ok": False,
            "checks": [],
            "summary": str(exc),
            "error": str(exc),
        }
    return _json_response(payload, status_code=200 if payload["ok"] else 503)


@router.get("/metrics")
def prometheus_metrics(request: Request, x_api_key: str = Header(None)):
    validate_api_key(request, x_api_key)
    body = observability.render_prometheus()
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4; charset=utf-8")


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

    return _checks_payload(results)


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
    job_id = prepare_job_context(request, "sync")
    audit_command_event(request, command="sync", outcome="started", summary={"days": days, "retries": retries})
    try:
        result = run_guarded_high_risk_operation(
            "sync",
            lambda: run_sync_with_retries(days=days, retries=retries),
            timeout_seconds=timeout,
            job_id=job_id,
        )
    except Exception as exc:
        audit_command_event(
            request,
            command="sync",
            outcome="failed",
            summary={"status_code": getattr(exc, "status_code", 500), "error": str(getattr(exc, "detail", exc))},
            level="ERROR",
        )
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(exc))

    response = {
        "success": result.success,
        "attempts": result.attempts,
        "failed_sources": result.failed_sources,
        "source_statuses": result.source_statuses,
        "undelivered_alerts": result.undelivered_alerts,
        "label": result.label,
        "summary": result.summary_line(days=days),
    }
    audit_command_event(request, command="sync", outcome="succeeded", summary=response)
    return response
