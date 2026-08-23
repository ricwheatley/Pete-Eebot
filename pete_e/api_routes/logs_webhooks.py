import datetime
import hashlib
import hmac
import json
import re

import fastapi
from fastapi import Header, HTTPException, Query, Request

from pete_e.api_routes.dependencies import (
    audit_command_event,
    configured_deploy_dispatch_command,
    configured_webhook_secret,
    enforce_command_rate_limit,
    get_edge_security_repository,
    get_job_service,
    prepare_job_context,
    validate_api_key,
)
from pete_e.api_errors import get_or_create_correlation_id
from pete_e.config import settings

router = fastapi.APIRouter()

ZERO_COMMIT_SHA = "0" * 40
COMMIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
DELIVERY_ID_PATTERN = re.compile(r"[A-Za-z0-9-]{1,128}")


def _configured_repository_id() -> int:
    repository_id = getattr(settings, "PETEEEBOT_GITHUB_REPOSITORY_ID", None)
    if repository_id is None or int(repository_id) <= 0:
        raise HTTPException(status_code=503, detail="PETEEEBOT_GITHUB_REPOSITORY_ID is not configured")
    return int(repository_id)


def _configured_deploy_ref() -> str:
    deploy_ref = str(getattr(settings, "PETEEEBOT_GITHUB_DEPLOY_REF", "") or "").strip()
    if deploy_ref != "refs/heads/main":
        raise HTTPException(status_code=503, detail="PETEEEBOT_GITHUB_DEPLOY_REF must be refs/heads/main")
    return deploy_ref


async def _read_bounded_body(request: Request) -> bytes:
    maximum = int(settings.PETEEEBOT_WEBHOOK_MAX_BODY_BYTES)
    raw_length = request.headers.get("Content-Length")
    if raw_length is not None:
        try:
            content_length = int(raw_length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc
        if content_length < 0:
            raise HTTPException(status_code=400, detail="Invalid Content-Length")
        if content_length > maximum:
            raise HTTPException(status_code=413, detail="Webhook body too large")

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > maximum:
            raise HTTPException(status_code=413, detail="Webhook body too large")
        body.extend(chunk)
    return bytes(body)


def _reject_webhook(message: str) -> None:
    raise HTTPException(
        status_code=422,
        detail={"code": "invalid_webhook", "message": message},
    )


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
    signature = request.headers.get("X-Hub-Signature-256")
    if not signature:
        raise HTTPException(status_code=403, detail="Missing signature")
    try:
        sha_name, sig = signature.split("=")
    except ValueError:
        raise HTTPException(status_code=403, detail="Bad signature format")
    if sha_name != "sha256":
        raise HTTPException(status_code=403, detail="Unsupported signature type")

    body = await _read_bounded_body(request)
    mac = hmac.new(configured_webhook_secret(), msg=body, digestmod=hashlib.sha256)
    if not hmac.compare_digest(mac.hexdigest(), sig):
        raise HTTPException(status_code=403, detail="Invalid signature")

    if getattr(request, "state", None) is not None:
        setattr(request.state, "auth_scheme", "github_webhook_hmac")
    event_name = str(request.headers.get("X-GitHub-Event") or "")
    delivery_id = str(request.headers.get("X-GitHub-Delivery") or "")
    if DELIVERY_ID_PATTERN.fullmatch(delivery_id) is None:
        _reject_webhook("Missing or invalid X-GitHub-Delivery")
    try:
        decoded_payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
    if not isinstance(decoded_payload, dict):
        raise HTTPException(status_code=400, detail="JSON payload must be an object")
    payload: dict[str, object] = decoded_payload

    expected_repository_id = _configured_repository_id()
    deploy_ref = _configured_deploy_ref()
    repository = payload.get("repository")
    repository_id = repository.get("id") if isinstance(repository, dict) else None
    commit_sha = payload.get("after")
    ref_name = payload.get("ref")

    if event_name != "push":
        _reject_webhook("X-GitHub-Event must be push")
    if type(repository_id) is not int or repository_id != expected_repository_id:
        _reject_webhook("Webhook repository identity does not match")
    if not isinstance(ref_name, str) or ref_name != deploy_ref:
        _reject_webhook(f"Webhook ref must be {deploy_ref}")
    if payload.get("deleted") is not False:
        _reject_webhook("Deleted refs cannot trigger deployment")
    if (
        not isinstance(commit_sha, str)
        or commit_sha == ZERO_COMMIT_SHA
        or COMMIT_SHA_PATTERN.fullmatch(commit_sha) is None
    ):
        _reject_webhook("Webhook after must be a non-zero lowercase 40-hex commit SHA")

    summary = {
        "source": "github_webhook",
        "delivery_id": delivery_id,
        "event": event_name,
        "repository_id": repository_id,
        "commit_sha": commit_sha,
        "ref": ref_name,
    }
    job_id = prepare_job_context(request, "deploy")
    try:
        delivery_claim = get_edge_security_repository().claim_github_delivery(
            delivery_id=delivery_id,
            repository_id=expected_repository_id,
            event_name=event_name,
            ref_name=ref_name,
            commit_sha=commit_sha,
            job_id=job_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Webhook delivery ledger is unavailable") from exc
    if not delivery_claim.accepted:
        response = {
            "status": "Webhook delivery already processed",
            "delivery_id": delivery_id,
            "job_id": delivery_claim.job_id,
            "delivery_status": delivery_claim.status,
        }
        audit_command_event(request, command="deploy", outcome="succeeded", summary=response)
        return response

    try:
        enforce_command_rate_limit(request, "deploy")
    except Exception as exc:
        get_edge_security_repository().mark_github_delivery(
            delivery_id,
            status="failed",
            failure_reason=str(getattr(exc, "detail", exc))[:1000],
        )
        raise
    audit_command_event(request, command="deploy", outcome="started", summary=summary)
    try:
        correlation_id = get_or_create_correlation_id(request)
        get_job_service().dispatch_external(
            job_id=job_id,
            operation="deploy",
            dispatch_command=configured_deploy_dispatch_command(job_id),
            requester=None,
            request_id=correlation_id,
            correlation_id=correlation_id,
            request_summary=summary,
            auth_scheme=getattr(getattr(request, "state", None), "auth_scheme", None),
            dispatch_timeout_seconds=settings.PETEEEBOT_DEPLOY_DISPATCH_TIMEOUT_SECONDS,
        )
    except HTTPException as exc:
        detail = getattr(exc, "detail", {})
        if getattr(exc, "status_code", None) == 409 and isinstance(detail, dict) and detail.get("code") == "operation_in_progress":
            ignored = {
                "status": "Deployment already in progress; webhook delivery ignored.",
                "job_id": job_id,
                "delivery_id": delivery_id,
                "commit_sha": commit_sha,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            }
            get_edge_security_repository().mark_github_delivery(delivery_id, status="ignored")
            audit_command_event(request, command="deploy", outcome="succeeded", summary=ignored)
            return ignored
        get_edge_security_repository().mark_github_delivery(
            delivery_id,
            status="failed",
            failure_reason=str(getattr(exc, "detail", exc))[:1000],
        )
        audit_command_event(
            request,
            command="deploy",
            outcome="failed",
            summary={"status_code": getattr(exc, "status_code", 500), "error": str(getattr(exc, "detail", exc))},
            level="ERROR",
        )
        raise
    except Exception as exc:
        get_edge_security_repository().mark_github_delivery(
            delivery_id,
            status="failed",
            failure_reason=str(exc)[:1000],
        )
        audit_command_event(
            request,
            command="deploy",
            outcome="failed",
            summary={"status_code": getattr(exc, "status_code", 500), "error": str(getattr(exc, "detail", exc))},
            level="ERROR",
        )
        raise

    get_edge_security_repository().mark_github_delivery(delivery_id, status="dispatched")
    response = {
        "status": "Deployment triggered",
        "job_id": job_id,
        "status_url": f"/console/jobs/{job_id}",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    audit_command_event(request, command="deploy", outcome="succeeded", summary=response)
    return response
