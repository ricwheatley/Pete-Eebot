import concurrent.futures
import hashlib
import hmac
import math
import secrets
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
from pete_e.domain.auth import AuthUser, RoleName, normalize_role
from pete_e.infrastructure.postgres_dal import PostgresDal
from pete_e.infrastructure.user_repository import PostgresUserRepository

T = TypeVar("T")

DEFAULT_COMMAND_RATE_LIMIT_MAX_REQUESTS = int(get_env("PETEEEBOT_COMMAND_RATE_LIMIT_MAX_REQUESTS", 10))
DEFAULT_COMMAND_RATE_LIMIT_WINDOW_SECONDS = float(get_env("PETEEEBOT_COMMAND_RATE_LIMIT_WINDOW_SECONDS", 60.0))
DEFAULT_SYNC_TIMEOUT_SECONDS = float(get_env("PETEEEBOT_SYNC_TIMEOUT_SECONDS", 300.0))
DEFAULT_PROCESS_TIMEOUT_SECONDS = float(get_env("PETEEEBOT_PROCESS_TIMEOUT_SECONDS", 900.0))
CSRF_HEADER_NAME = "X-CSRF-Token"
SAFE_HTTP_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

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


def session_cookie_name() -> str:
    return str(get_env("PETEEEBOT_SESSION_COOKIE_NAME", "peteeebot_session") or "peteeebot_session")


def csrf_cookie_name() -> str:
    return str(get_env("PETEEEBOT_CSRF_COOKIE_NAME", "peteeebot_csrf") or "peteeebot_csrf")


def csrf_header_name() -> str:
    return CSRF_HEADER_NAME


def session_cookie_samesite() -> str:
    candidate = str(get_env("PETEEEBOT_SESSION_COOKIE_SAMESITE", "lax") or "lax").strip().lower()
    return candidate if candidate in {"lax", "strict", "none"} else "lax"


def session_cookie_secure() -> bool:
    configured = getattr(settings, "PETEEEBOT_SESSION_COOKIE_SECURE", None)
    if configured is not None:
        return bool(configured)

    environment = str(get_env("ENVIRONMENT", "development") or "development").strip().lower()
    return environment not in {"dev", "development", "local", "test", "testing"}


def _cookie_domain() -> str | None:
    value = get_env("PETEEEBOT_SESSION_COOKIE_DOMAIN", None)
    candidate = str(value).strip() if value else ""
    return candidate or None


def _request_cookie(request: Request, name: str) -> str | None:
    cookies = getattr(request, "cookies", None)
    if isinstance(cookies, dict):
        value = cookies.get(name)
        return str(value) if value else None

    headers = getattr(request, "headers", {}) or {}
    raw_cookie = headers.get("cookie") or headers.get("Cookie") or ""
    for part in str(raw_cookie).split(";"):
        cookie_name, separator, value = part.strip().partition("=")
        if separator and cookie_name == name and value:
            return value
    return None


def session_token_from_request(request: Request) -> str | None:
    return _request_cookie(request, session_cookie_name())


def _header_value(request: Request, name: str) -> str | None:
    headers = getattr(request, "headers", {}) or {}
    if name in headers:
        return str(headers[name])

    lower_name = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lower_name:
            return str(value)
    return None


def generate_csrf_token(session_token: str) -> str:
    nonce = secrets.token_urlsafe(32)
    digest = hmac.new(
        session_token.encode("utf-8"),
        nonce.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{nonce}.{digest}"


def _valid_csrf_token(session_token: str, csrf_token: str) -> bool:
    nonce, separator, digest = str(csrf_token or "").partition(".")
    if not separator or not nonce or not digest:
        return False
    expected = hmac.new(
        session_token.encode("utf-8"),
        nonce.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(digest, expected)


def csrf_token_from_request(request: Request) -> str | None:
    header_token = _header_value(request, CSRF_HEADER_NAME)
    cookie_token = _request_cookie(request, csrf_cookie_name())
    if not header_token or not cookie_token:
        return None
    if not hmac.compare_digest(str(header_token), str(cookie_token)):
        return None
    return str(header_token)


def set_session_cookies(response, session_token: str, csrf_token: str) -> None:
    cookie_kwargs = {
        "path": "/",
        "domain": _cookie_domain(),
        "secure": session_cookie_secure(),
        "samesite": session_cookie_samesite(),
    }
    set_cookie = getattr(response, "set_cookie", None)
    if not callable(set_cookie):
        return

    set_cookie(
        key=session_cookie_name(),
        value=session_token,
        httponly=True,
        **cookie_kwargs,
    )
    set_cookie(
        key=csrf_cookie_name(),
        value=csrf_token,
        httponly=False,
        **cookie_kwargs,
    )


def clear_session_cookies(response) -> None:
    cookie_kwargs = {
        "path": "/",
        "domain": _cookie_domain(),
        "secure": session_cookie_secure(),
        "samesite": session_cookie_samesite(),
    }
    delete_cookie = getattr(response, "delete_cookie", None)
    if callable(delete_cookie):
        delete_cookie(key=session_cookie_name(), httponly=True, **cookie_kwargs)
        delete_cookie(key=csrf_cookie_name(), httponly=False, **cookie_kwargs)


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


def _request_method(request: Request) -> str:
    return str(getattr(request, "method", "GET") or "GET").upper()


def _mark_authenticated_request(request: Request, *, scheme: str, user: AuthUser | None = None) -> None:
    state = getattr(request, "state", None)
    if state is None:
        return
    setattr(state, "auth_scheme", scheme)
    if user is not None:
        setattr(state, "auth_user", user)


def current_user_from_session(request: Request) -> AuthUser | None:
    token = session_token_from_request(request)
    if not token:
        return None

    user = get_user_service().validate_session_token(token)
    if user is not None:
        _mark_authenticated_request(request, scheme="session", user=user)
    return user


def enforce_csrf_for_session(request: Request, session_token: str | None = None) -> None:
    token = session_token or session_token_from_request(request)
    csrf_token = csrf_token_from_request(request)
    if not token or not csrf_token:
        raise HTTPException(
            status_code=403,
            detail={"code": "csrf_required", "message": "Missing CSRF token"},
        )
    if not _valid_csrf_token(token, csrf_token):
        raise HTTPException(
            status_code=403,
            detail={"code": "csrf_invalid", "message": "Invalid CSRF token"},
        )


def require_browser_user(request: Request, *, require_csrf: bool = False) -> AuthUser:
    token = session_token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    user = get_user_service().validate_session_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    if require_csrf:
        enforce_csrf_for_session(request, token)

    _mark_authenticated_request(request, scheme="session", user=user)
    return user


def require_role(request: Request, role: RoleName | str, *, require_csrf: bool = False) -> AuthUser:
    user = require_browser_user(request, require_csrf=require_csrf)
    if not user.has_role(normalize_role(str(role))):
        raise HTTPException(status_code=403, detail="Insufficient role")
    return user


def validate_api_key(request: Request, x_api_key: str | None = Header(None)) -> None:
    key = x_api_key
    if key:
        if hmac.compare_digest(key, configured_api_key()):
            _mark_authenticated_request(request, scheme="api_key")
            return
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    token = session_token_from_request(request)
    if token:
        user = get_user_service().validate_session_token(token)
        if user is not None:
            if _request_method(request) not in SAFE_HTTP_METHODS:
                enforce_csrf_for_session(request, token)
            _mark_authenticated_request(request, scheme="session", user=user)
            return

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
