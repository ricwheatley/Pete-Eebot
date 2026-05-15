from pathlib import Path
import hmac
import subprocess
import threading
from typing import Callable, TypeVar

from fastapi import Header, HTTPException, Request

from pete_e.application.api_services import MetricsService, PlanService, StatusService
from pete_e.application.concurrency_guard import OperationInProgress, high_risk_operation_guard
from pete_e.application.nutrition_service import NutritionService
from pete_e.config import settings
from pete_e.infrastructure.postgres_dal import PostgresDal

T = TypeVar("T")

_dal: PostgresDal | None = None
_metrics_service: MetricsService | None = None
_nutrition_service: NutritionService | None = None
_plan_service: PlanService | None = None
_status_service: StatusService | None = None


def _secret_to_str(value) -> str:
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        return getter()
    return "" if value is None else str(value)


def configured_api_key() -> str:
    configured = (settings.PETEEEBOT_API_KEY or "").strip()
    if not configured:
        raise HTTPException(status_code=503, detail="PETEEEBOT_API_KEY is not configured")
    return configured


def configured_webhook_secret() -> bytes:
    secret = _secret_to_str(getattr(settings, "GITHUB_WEBHOOK_SECRET", None)).strip()
    if not secret:
        raise HTTPException(status_code=503, detail="GITHUB_WEBHOOK_SECRET is not configured")
    return secret.encode("utf-8")


def configured_deploy_script_path() -> Path:
    raw_path = getattr(settings, "DEPLOY_SCRIPT_PATH", None)
    deploy_path = Path(str(raw_path)).expanduser() if raw_path else None
    if deploy_path is None or not str(deploy_path).strip():
        raise HTTPException(status_code=503, detail="DEPLOY_SCRIPT_PATH is not configured")
    if not deploy_path.exists():
        raise HTTPException(status_code=500, detail=f"Deploy script not found: {deploy_path}")
    return deploy_path


def get_dal() -> PostgresDal:
    global _dal
    if _dal is None:
        _dal = PostgresDal()
    return _dal


def get_metrics_service() -> MetricsService:
    global _metrics_service
    if _metrics_service is None:
        _metrics_service = MetricsService(get_dal())
    return _metrics_service


def get_nutrition_service() -> NutritionService:
    global _nutrition_service
    if _nutrition_service is None:
        _nutrition_service = NutritionService(get_dal())
    return _nutrition_service


def get_plan_service() -> PlanService:
    global _plan_service
    if _plan_service is None:
        _plan_service = PlanService(get_dal())
    return _plan_service


def get_status_service() -> StatusService:
    global _status_service
    if _status_service is None:
        _status_service = StatusService(get_dal())
    return _status_service


def validate_api_key(request: Request, x_api_key: str | None = Header(None)) -> None:
    configured_key = configured_api_key()
    key = x_api_key or request.query_params.get("api_key")
    if not key or not hmac.compare_digest(key, configured_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _operation_conflict(exc: OperationInProgress) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "message": str(exc),
            "requested_operation": exc.requested_operation,
            "active_operation": exc.active_operation,
        },
    )


def run_guarded_high_risk_operation(operation: str, callback: Callable[[], T]) -> T:
    try:
        return high_risk_operation_guard.run(operation, callback)
    except OperationInProgress as exc:
        raise _operation_conflict(exc) from exc


def start_guarded_high_risk_process(
    operation: str,
    command: list[str],
) -> subprocess.Popen:
    try:
        high_risk_operation_guard.acquire(operation)
    except OperationInProgress as exc:
        raise _operation_conflict(exc) from exc

    try:
        process = subprocess.Popen(command)
    except Exception:
        high_risk_operation_guard.release()
        raise

    def _release_when_finished() -> None:
        try:
            process.wait()
        finally:
            high_risk_operation_guard.release()

    threading.Thread(
        target=_release_when_finished,
        name=f"{operation}-guard-release",
        daemon=True,
    ).start()
    return process
