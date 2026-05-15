import datetime
import hashlib
import hmac

import fastapi
from fastapi import Header, HTTPException, Query, Request

from pete_e.api_routes.dependencies import (
    audit_command_event,
    configured_deploy_script_path,
    configured_webhook_secret,
    enforce_command_rate_limit,
    get_job_service,
    prepare_job_context,
    validate_api_key,
)
from pete_e.api_errors import get_or_create_correlation_id
from pete_e.config import settings

router = fastapi.APIRouter() if hasattr(fastapi, "APIRouter") else fastapi.FastAPI()


def read_recent_log_lines(lines: int) -> dict[str, object]:
    log_path = settings.log_path
    if not log_path.exists():
        raise HTTPException(status_code=404, detail=f"Log file not found: {log_path}")
    try:
        with log_path.open("r", encoding="utf-8") as log_file:
            log_lines = log_file.readlines()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {"path": str(log_path), "lines": [line.rstrip("\n") for line in log_lines[-lines:]]}


@router.get("/logs")
def logs(request: Request, x_api_key: str = Header(None), lines: int = Query(50, ge=1, le=1000)):
    validate_api_key(request, x_api_key)
    return read_recent_log_lines(lines)


@router.post("/webhook")
async def github_webhook(request: Request):
    enforce_command_rate_limit(request, "deploy")
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    if not signature:
        raise HTTPException(status_code=403, detail="Missing signature")
    try:
        sha_name, sig = signature.split("=")
    except ValueError:
        raise HTTPException(status_code=403, detail="Bad signature format")
    if sha_name != "sha256":
        raise HTTPException(status_code=403, detail="Unsupported signature type")

    mac = hmac.new(configured_webhook_secret(), msg=body, digestmod=hashlib.sha256)
    if not hmac.compare_digest(mac.hexdigest(), sig):
        raise HTTPException(status_code=403, detail="Invalid signature")

    if getattr(request, "state", None) is not None:
        setattr(request.state, "auth_scheme", "github_webhook_hmac")
    job_id = prepare_job_context(request, "deploy")
    summary = {"source": "github_webhook"}
    audit_command_event(request, command="deploy", outcome="started", summary=summary)
    try:
        correlation_id = get_or_create_correlation_id(request)
        get_job_service().enqueue_subprocess(
            job_id=job_id,
            operation="deploy",
            command=[str(configured_deploy_script_path())],
            requester=None,
            request_id=correlation_id,
            correlation_id=correlation_id,
            request_summary=summary,
            timeout_seconds=getattr(settings, "PETEEEBOT_PROCESS_TIMEOUT_SECONDS", None),
            auth_scheme=getattr(getattr(request, "state", None), "auth_scheme", None),
        )
    except Exception as exc:
        audit_command_event(
            request,
            command="deploy",
            outcome="failed",
            summary={"status_code": getattr(exc, "status_code", 500), "error": str(getattr(exc, "detail", exc))},
            level="ERROR",
        )
        raise

    response = {
        "status": "Deployment triggered",
        "job_id": job_id,
        "status_url": f"/console/jobs/{job_id}",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    audit_command_event(request, command="deploy", outcome="succeeded", summary=response)
    return response
