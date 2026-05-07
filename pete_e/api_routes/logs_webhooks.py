import datetime
import hashlib
import hmac
import subprocess

import fastapi
from fastapi import Header, HTTPException, Query, Request

from pete_e.api_routes.dependencies import (
    configured_deploy_script_path,
    configured_webhook_secret,
    validate_api_key,
)
from pete_e.config import settings

router = fastapi.APIRouter() if hasattr(fastapi, "APIRouter") else fastapi.FastAPI()


@router.get("/logs")
def logs(request: Request, x_api_key: str = Header(None), lines: int = Query(50, ge=1, le=1000)):
    validate_api_key(request, x_api_key)
    log_path = settings.log_path
    if not log_path.exists():
        raise HTTPException(status_code=404, detail=f"Log file not found: {log_path}")
    try:
        with log_path.open("r", encoding="utf-8") as log_file:
            log_lines = log_file.readlines()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {"path": str(log_path), "lines": [line.rstrip("\n") for line in log_lines[-lines:]]}


@router.post("/webhook")
async def github_webhook(request: Request):
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

    subprocess.Popen([str(configured_deploy_script_path())])

    return {
        "status": "Deployment triggered",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
    }
