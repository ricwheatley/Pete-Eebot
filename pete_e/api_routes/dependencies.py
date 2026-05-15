import concurrent.futures
import hmac
import math
from pathlib import Path
import subprocess
import threading
import time
from typing import Callable, TypeVar

from fastapi import Header, HTTPException, Request

from pete_e.application.api_services import MetricsService, PlanService, StatusService
from pete_e.application.concurrency_guard import OperationInProgress, high_risk_operation_guard
from pete_e.application.nutrition_service import NutritionService
from pete_e.application.user_service import UserService
from pete_e.config import get_env, settings
from pete_e.infrastructure.postgres_dal import PostgresDal
from pete_e.infrastructure.user_repository import PostgresUserRepository

T = TypeVar("T")

DEFAULT_COMMAND_RATE_LIMIT_MAX_REQUESTS = int(get_env("PETEEEBOT_COMMAND_RATE_LIMIT_MAX_REQUESTS", 10))
DEFAULT_COMMAND_RATE_LIMIT_WINDOW_SECONDS = float(get_env("PETEEEBOT_COMMAND_RATE_LIMIT_WINDOW_SECONDS", 60.0))
DEFAULT_SYNC_TIMEOUT_SECONDS = float(get_env("PETEEEBOT_SYNC_TIMEOUT_SECONDS", 300.0))
DEFAULT_PROCESS_TIMEOUT_SECONDS = float(get_env("PETEEEBOT_PROCESS_TIMEOUT_SECONDS", 900.0))

_dal: PostgresDal | None = None
_metrics_service: MetricsService | None = None
_nutrition_service: NutritionService | None = None
_plan_service: PlanService | None = None
_status_service: StatusService | None = None
_user_service: UserService | None = None
_command_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="api-command",
)
_rate_limit_lock = threading.Lock()
_rate_limit_events: dict[tuple[str, str], list[float]] = {}


def _http_exception(status_code: int, detail, headers: dict[str, str] | None = None) -> HTTPException:
    try:
        return HTTPException(status_code=status_code, detail=detail, headers=headers)
    except TypeError:
        return HTTPException(status_code=status_code, detail=detail)


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


def get_user_service() -> UserService:
    global _user_service
    if _user_service is None:
        dal = get_dal()
        _user_service = UserService(PostgresUserRepository(pool=dal.pool))
    return _user_service


def validate_api_key(request: Request, x_api_key: str | None = Header(None)) -> None:
    configured_key = configured_api_key()
    key = x_api_key
    if not key or not hmac.compare_digest(key, configured_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _client_identity(request: Request) -> str:
    headers = getattr(request, "headers", {}) or {}
    forwarded_for = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    return str(host or "local")


def reset_command_rate_limits() -> None:
    with _rate_limit_lock:
        _rate_limit_events.clear()


def enforce_command_rate_limit(
    request: Request,
    operation: str,
    *,
    max_requests: int = DEFAULT_COMMAND_RATE_LIMIT_MAX_REQUESTS,
    window_seconds: float = DEFAULT_COMMAND_RATE_LIMIT_WINDOW_SECONDS,
) -> None:
    if max_requests <= 0 or window_seconds <= 0:
        return

    now = time.monotonic()
    key = (operation, _client_identity(request))
    with _rate_limit_lock:
        events = [timestamp for timestamp in _rate_limit_events.get(key, []) if now - timestamp < window_seconds]
        if len(events) >= max_requests:
            retry_after = max(1, math.ceil(window_seconds - (now - events[0])))
            _rate_limit_events[key] = events
            raise _http_exception(
                status_code=429,
                detail={
                    "code": "rate_limited",
                    "message": f"Rate limit exceeded for {operation}",
                    "operation": operation,
                    "retry_after_seconds": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )
        events.append(now)
        _rate_limit_events[key] = events


def _operation_conflict(exc: OperationInProgress) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "operation_in_progress",
            "message": str(exc),
            "requested_operation": exc.requested_operation,
            "active_operation": exc.active_operation,
        },
    )


def run_guarded_high_risk_operation(
    operation: str,
    callback: Callable[[], T],
    *,
    timeout_seconds: float | None = None,
) -> T:
    if timeout_seconds is None or timeout_seconds <= 0:
        try:
            return high_risk_operation_guard.run(operation, callback)
        except OperationInProgress as exc:
            raise _operation_conflict(exc) from exc

    try:
        high_risk_operation_guard.acquire(operation)
    except OperationInProgress as exc:
        raise _operation_conflict(exc) from exc

    def _run_and_release() -> T:
        try:
            return callback()
        finally:
            high_risk_operation_guard.release()

    future = _command_executor.submit(_run_and_release)
    try:
        return future.result(timeout=timeout_seconds)
    except concurrent.futures.TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail={
                "code": "command_timeout",
                "message": f"{operation} exceeded {timeout_seconds:g}s timeout",
                "operation": operation,
                "timeout_seconds": timeout_seconds,
            },
        ) from exc


def start_guarded_high_risk_process(
    operation: str,
    command: list[str],
    *,
    timeout_seconds: float | None = DEFAULT_PROCESS_TIMEOUT_SECONDS,
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
            try:
                if timeout_seconds is None or timeout_seconds <= 0:
                    process.wait()
                else:
                    process.wait(timeout=timeout_seconds)
            except TypeError:
                process.wait()
            except subprocess.TimeoutExpired:
                terminate = getattr(process, "terminate", None)
                if callable(terminate):
                    terminate()
                try:
                    process.wait(timeout=10)
                except Exception:
                    kill = getattr(process, "kill", None)
                    if callable(kill):
                        kill()
                    process.wait()
        finally:
            high_risk_operation_guard.release()

    threading.Thread(
        target=_release_when_finished,
        name=f"{operation}-guard-release",
        daemon=True,
    ).start()
    return process
