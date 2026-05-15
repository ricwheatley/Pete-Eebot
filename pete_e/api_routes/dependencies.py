import concurrent.futures
import contextvars
from dataclasses import dataclass, field
import hashlib
import hmac
import math
import secrets
from pathlib import Path
import subprocess
import threading
import time
import uuid
from typing import Any, Callable, Mapping, TypeVar

from fastapi import Header, HTTPException, Request

from pete_e.api_errors import get_or_create_correlation_id
from pete_e.api_logging import session_fingerprint
from pete_e.application.api_services import MetricsService, PlanService, StatusService
from pete_e.application import alerts
from pete_e.application.concurrency_guard import OperationInProgress, high_risk_operation_guard
from pete_e.application.nutrition_service import NutritionService
from pete_e.application.profile_service import ProfileService
from pete_e.application.user_service import UserService, normalize_login
from pete_e.config import get_env, settings
from pete_e.domain.auth import AuthUser, ROLE_OPERATOR, ROLE_OWNER, ROLE_READ_ONLY, RoleName, normalize_role
from pete_e.infrastructure import log_utils
from pete_e.logging_setup import bind_log_context, reset_log_context
from pete_e.infrastructure.postgres_dal import PostgresDal
from pete_e.infrastructure.profile_repository import PostgresProfileRepository
from pete_e.infrastructure.user_repository import PostgresUserRepository
from pete_e import observability

T = TypeVar("T")

DEFAULT_COMMAND_RATE_LIMIT_MAX_REQUESTS = int(get_env("PETEEEBOT_COMMAND_RATE_LIMIT_MAX_REQUESTS", 10))
DEFAULT_COMMAND_RATE_LIMIT_WINDOW_SECONDS = float(get_env("PETEEEBOT_COMMAND_RATE_LIMIT_WINDOW_SECONDS", 60.0))
DEFAULT_LOGIN_RATE_LIMIT_MAX_ATTEMPTS = int(get_env("PETEEEBOT_LOGIN_RATE_LIMIT_MAX_ATTEMPTS", 5))
DEFAULT_LOGIN_RATE_LIMIT_WINDOW_SECONDS = float(get_env("PETEEEBOT_LOGIN_RATE_LIMIT_WINDOW_SECONDS", 300.0))
DEFAULT_LOGIN_LOCKOUT_SECONDS = float(get_env("PETEEEBOT_LOGIN_LOCKOUT_SECONDS", 900.0))
DEFAULT_LOGIN_BACKOFF_BASE_SECONDS = float(get_env("PETEEEBOT_LOGIN_BACKOFF_BASE_SECONDS", 1.0))
DEFAULT_SYNC_TIMEOUT_SECONDS = float(get_env("PETEEEBOT_SYNC_TIMEOUT_SECONDS", 300.0))
DEFAULT_PROCESS_TIMEOUT_SECONDS = float(get_env("PETEEEBOT_PROCESS_TIMEOUT_SECONDS", 900.0))
CSRF_HEADER_NAME = "X-CSRF-Token"
SAFE_HTTP_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
MACHINE_API_KEY_EXACT_PATHS = frozenset(
    {
        "/metrics_overview",
        "/daily_summary",
        "/recent_workouts",
        "/coach_state",
        "/goal_state",
        "/user_notes",
        "/plan_context",
        "/sse",
        "/metrics",
        "/nutrition/daily-summary",
        "/nutrition/log-macros",
        "/plan_for_day",
        "/plan_for_week",
        "/plan_decision_trace",
        "/run_pete_plan_async",
        "/status",
        "/sync",
        "/logs",
    }
)
MACHINE_API_KEY_PREFIX_PATHS = frozenset({"/nutrition/log-macros/"})

_dal: PostgresDal | None = None
_metrics_service: MetricsService | None = None
_nutrition_service: NutritionService | None = None
_plan_service: PlanService | None = None
_status_service: StatusService | None = None
_user_service: UserService | None = None
_profile_service: ProfileService | None = None
_command_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="api-command",
)
_rate_limit_lock = threading.Lock()
_rate_limit_events: dict[tuple[str, str], list[float]] = {}
_login_attempt_lock = threading.Lock()


@dataclass
class _LoginAttemptState:
    failures: list[float] = field(default_factory=list)
    next_allowed_at: float = 0.0
    locked_until: float = 0.0


_login_attempts: dict[tuple[str, str], _LoginAttemptState] = {}


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
        _metrics_service = MetricsService(get_dal(), profile_service=get_profile_service())
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


def get_profile_service() -> ProfileService:
    global _profile_service
    if _profile_service is None:
        dal = get_dal()
        _profile_service = ProfileService(PostgresProfileRepository(pool=dal.pool))
    return _profile_service


def _request_method(request: Request) -> str:
    return str(getattr(request, "method", "GET") or "GET").upper()


def _request_path(request: Request) -> str | None:
    scope = getattr(request, "scope", None)
    if isinstance(scope, dict) and scope.get("path"):
        return str(scope["path"])

    url = getattr(request, "url", None)
    path = getattr(url, "path", None)
    if path:
        return str(path)

    path = getattr(request, "path", None)
    return str(path) if path else None


def _normalize_api_path(path: str | None) -> str | None:
    if not path:
        return None
    candidate = str(path).strip() or "/"
    if candidate.startswith("/api/v1/"):
        return candidate[len("/api/v1") :]
    if candidate == "/api/v1":
        return "/"
    return candidate


def _is_machine_api_key_path(request: Request) -> bool:
    path = _normalize_api_path(_request_path(request))
    if path is None:
        return True
    if path in MACHINE_API_KEY_EXACT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in MACHINE_API_KEY_PREFIX_PATHS)


def _mark_authenticated_request(request: Request, *, scheme: str, user: AuthUser | None = None) -> None:
    state = getattr(request, "state", None)
    if state is None:
        return
    setattr(state, "auth_scheme", scheme)
    fields: dict[str, Any] = {"auth_scheme": scheme}
    if user is not None:
        setattr(state, "auth_user", user)
        fields.update(
            {
                "user_id": user.id,
                "username": user.username,
                "roles": list(user.roles),
            }
        )
    if scheme == "session":
        fields["session_id"] = session_fingerprint(session_token_from_request(request))
    bind_log_context(**fields)


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
    if not _user_satisfies_role(user, normalize_role(str(role))):
        raise HTTPException(status_code=403, detail="Insufficient role")
    return user


def _user_satisfies_role(user: AuthUser, role: RoleName) -> bool:
    if role == ROLE_READ_ONLY:
        return True
    if role == ROLE_OPERATOR:
        return user.can_operate
    if role == ROLE_OWNER:
        return user.is_owner
    return user.has_role(role)


def validate_api_key(
    request: Request,
    x_api_key: str | None = Header(None),
    *,
    required_session_role: RoleName | str = ROLE_READ_ONLY,
) -> None:
    key = x_api_key
    if key:
        if not _is_machine_api_key_path(request):
            raise HTTPException(status_code=403, detail="API key is not accepted for this endpoint")
        if hmac.compare_digest(key, configured_api_key()):
            _mark_authenticated_request(request, scheme="api_key")
            return
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    token = session_token_from_request(request)
    if token:
        user = get_user_service().validate_session_token(token)
        if user is not None:
            required_role = normalize_role(str(required_session_role))
            if not _user_satisfies_role(user, required_role):
                raise HTTPException(status_code=403, detail="Insufficient role")
            if _request_method(request) not in SAFE_HTTP_METHODS:
                enforce_csrf_for_session(request, token)
            _mark_authenticated_request(request, scheme="session", user=user)
            return

    raise HTTPException(status_code=401, detail="Invalid or missing API key")


def reset_login_attempts() -> None:
    with _login_attempt_lock:
        _login_attempts.clear()


def _login_attempt_key(request: Request, login: str) -> tuple[str, str]:
    return (normalize_login(login) or "<blank>", _client_identity(request))


def _prune_login_failures(state: _LoginAttemptState, now: float, window_seconds: float) -> None:
    state.failures = [timestamp for timestamp in state.failures if now - timestamp < window_seconds]
    if not state.failures and state.locked_until <= now:
        state.next_allowed_at = 0.0
        state.locked_until = 0.0


def _raise_login_throttle(code: str, message: str, retry_after: int) -> None:
    raise _http_exception(
        status_code=429,
        detail={
            "code": code,
            "message": message,
            "retry_after_seconds": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    )


def enforce_login_attempt_allowed(request: Request, login: str) -> None:
    now = time.monotonic()
    window_seconds = DEFAULT_LOGIN_RATE_LIMIT_WINDOW_SECONDS
    key = _login_attempt_key(request, login)
    with _login_attempt_lock:
        state = _login_attempts.get(key)
        if state is None:
            return
        _prune_login_failures(state, now, window_seconds)
        if state.locked_until > now:
            retry_after = max(1, math.ceil(state.locked_until - now))
            _raise_login_throttle("login_locked", "Login temporarily locked", retry_after)
        if state.next_allowed_at > now:
            retry_after = max(1, math.ceil(state.next_allowed_at - now))
            _raise_login_throttle("login_backoff", "Login retry backoff active", retry_after)


def record_login_failure(request: Request, login: str) -> None:
    now = time.monotonic()
    max_attempts = DEFAULT_LOGIN_RATE_LIMIT_MAX_ATTEMPTS
    window_seconds = DEFAULT_LOGIN_RATE_LIMIT_WINDOW_SECONDS
    lockout_seconds = DEFAULT_LOGIN_LOCKOUT_SECONDS
    backoff_base_seconds = DEFAULT_LOGIN_BACKOFF_BASE_SECONDS
    if max_attempts <= 0 or window_seconds <= 0:
        return

    key = _login_attempt_key(request, login)
    with _login_attempt_lock:
        state = _login_attempts.setdefault(key, _LoginAttemptState())
        _prune_login_failures(state, now, window_seconds)
        state.failures.append(now)
        if len(state.failures) >= max_attempts and lockout_seconds > 0:
            state.locked_until = now + lockout_seconds
            state.next_allowed_at = state.locked_until
            retry_after = max(1, math.ceil(lockout_seconds))
            _raise_login_throttle("login_locked", "Login temporarily locked", retry_after)
        if backoff_base_seconds > 0:
            backoff_seconds = min(
                lockout_seconds if lockout_seconds > 0 else backoff_base_seconds * 16,
                backoff_base_seconds * (2 ** max(0, len(state.failures) - 1)),
            )
            state.next_allowed_at = now + backoff_seconds


def record_login_success(request: Request, login: str) -> None:
    key = _login_attempt_key(request, login)
    with _login_attempt_lock:
        _login_attempts.pop(key, None)


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


def audit_command_event(
    request: Request,
    *,
    command: str,
    outcome: str,
    summary: Mapping[str, Any] | None = None,
    level: str = "INFO",
) -> None:
    state = getattr(request, "state", None)
    user = getattr(state, "auth_user", None)
    auth_scheme = getattr(state, "auth_scheme", None)
    job_id = getattr(state, "job_id", None)
    user_summary = {}
    if isinstance(user, AuthUser):
        user_summary = {
            "user_id": user.id,
            "username": user.username,
            "roles": list(user.roles),
        }

    log_utils.log_checkpoint(
        checkpoint="operator_command",
        outcome=outcome,
        correlation={
            "command": command,
            "auth_scheme": auth_scheme,
            "client": _client_identity(request),
            "request_id": get_or_create_correlation_id(request),
            "correlation_id": get_or_create_correlation_id(request),
            "job_id": job_id,
            "session_id": session_fingerprint(session_token_from_request(request)),
            **user_summary,
        },
        summary=summary or {},
        level=level,
        tag="AUDIT",
    )


def new_job_id(operation: str) -> str:
    safe_operation = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in operation.lower()).strip("-")
    return f"{safe_operation or 'job'}-{uuid.uuid4().hex[:12]}"


def prepare_job_context(request: Request | None, operation: str) -> str:
    job_id = new_job_id(operation)
    if request is not None and getattr(request, "state", None) is not None:
        setattr(request.state, "job_id", job_id)
    bind_log_context(job_id=job_id, component="job")
    return job_id


def _log_job_event(
    *,
    operation: str,
    job_id: str,
    outcome: str,
    level: str = "INFO",
    summary: Mapping[str, Any] | None = None,
) -> None:
    log_utils.log_event(
        event="background_job",
        message=f"job {operation} {outcome}",
        tag="JOB",
        level=level,
        operation=operation,
        job_id=job_id,
        outcome=outcome,
        summary=summary or {},
    )


def _job_outcome_from_result(result: Any) -> str:
    return "failed" if getattr(result, "success", True) is False else "succeeded"


def _run_job_callback(operation: str, job_id: str, callback: Callable[[], T]) -> T:
    _log_job_event(operation=operation, job_id=job_id, outcome="started")
    started = time.perf_counter()
    try:
        result = callback()
    except Exception as exc:
        duration_seconds = time.perf_counter() - started
        observability.record_job_completed(
            operation=operation,
            outcome="failed",
            duration_seconds=duration_seconds,
        )
        alerts.record_operation_outcome(
            operation=operation,
            outcome="failed",
            job_id=job_id,
            context={"error": str(exc), "duration_ms": round(duration_seconds * 1000, 2)},
        )
        _log_job_event(
            operation=operation,
            job_id=job_id,
            outcome="failed",
            level="ERROR",
            summary={"duration_ms": round(duration_seconds * 1000, 2), "error": str(exc)},
        )
        raise
    duration_seconds = time.perf_counter() - started
    outcome = _job_outcome_from_result(result)
    observability.record_job_completed(
        operation=operation,
        outcome=outcome,
        duration_seconds=duration_seconds,
    )
    alerts.record_operation_outcome(
        operation=operation,
        outcome=outcome,
        job_id=job_id,
        context={"duration_ms": round(duration_seconds * 1000, 2)},
    )
    _log_job_event(
        operation=operation,
        job_id=job_id,
        outcome=outcome,
        level="INFO" if outcome == "succeeded" else "ERROR",
        summary={"duration_ms": round(duration_seconds * 1000, 2)},
    )
    return result


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
    job_id: str | None = None,
) -> T:
    job_id = job_id or new_job_id(operation)
    if timeout_seconds is None or timeout_seconds <= 0:
        token = bind_log_context(job_id=job_id, component="job")
        try:
            return high_risk_operation_guard.run(
                operation,
                lambda: _run_job_callback(operation, job_id, callback),
            )
        except OperationInProgress as exc:
            raise _operation_conflict(exc) from exc
        finally:
            reset_log_context(token)

    try:
        high_risk_operation_guard.acquire(operation)
    except OperationInProgress as exc:
        raise _operation_conflict(exc) from exc

    parent_token = bind_log_context(job_id=job_id, component="job")
    worker_context = contextvars.copy_context()
    reset_log_context(parent_token)

    def _run_and_release() -> T:
        try:
            return _run_job_callback(operation, job_id, callback)
        finally:
            high_risk_operation_guard.release()

    future = _command_executor.submit(worker_context.run, _run_and_release)
    started = time.perf_counter()
    try:
        return future.result(timeout=timeout_seconds)
    except concurrent.futures.TimeoutError as exc:
        observability.record_job_completed(
            operation=operation,
            outcome="timeout",
            duration_seconds=time.perf_counter() - started,
        )
        alerts.record_operation_outcome(
            operation=operation,
            outcome="timeout",
            job_id=job_id,
            context={"timeout_seconds": timeout_seconds},
        )
        _log_job_event(
            operation=operation,
            job_id=job_id,
            outcome="timeout",
            level="ERROR",
            summary={"timeout_seconds": timeout_seconds},
        )
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
    job_id: str | None = None,
) -> subprocess.Popen:
    job_id = job_id or new_job_id(operation)
    try:
        high_risk_operation_guard.acquire(operation)
    except OperationInProgress as exc:
        raise _operation_conflict(exc) from exc

    try:
        _log_job_event(
            operation=operation,
            job_id=job_id,
            outcome="started",
            summary={"command": command[:1]},
        )
        process = subprocess.Popen(command)
    except Exception:
        observability.record_job_completed(
            operation=operation,
            outcome="failed",
            duration_seconds=0.0,
        )
        alerts.record_operation_outcome(operation=operation, outcome="failed", job_id=job_id)
        high_risk_operation_guard.release()
        raise

    def _release_when_finished() -> None:
        started = time.perf_counter()
        try:
            try:
                if timeout_seconds is None or timeout_seconds <= 0:
                    return_code = process.wait()
                else:
                    return_code = process.wait(timeout=timeout_seconds)
                outcome = "succeeded" if return_code == 0 else "failed"
                duration_seconds = time.perf_counter() - started
                observability.record_job_completed(
                    operation=operation,
                    outcome=outcome,
                    duration_seconds=duration_seconds,
                )
                alerts.record_operation_outcome(
                    operation=operation,
                    outcome=outcome,
                    job_id=job_id,
                    context={"return_code": return_code, "duration_ms": round(duration_seconds * 1000, 2)},
                )
                _log_job_event(
                    operation=operation,
                    job_id=job_id,
                    outcome=outcome,
                    level="INFO" if return_code == 0 else "ERROR",
                    summary={
                        "return_code": return_code,
                        "duration_ms": round(duration_seconds * 1000, 2),
                    },
                )
            except TypeError:
                return_code = process.wait()
                outcome = "succeeded" if return_code == 0 else "failed"
                observability.record_job_completed(
                    operation=operation,
                    outcome=outcome,
                    duration_seconds=time.perf_counter() - started,
                )
                alerts.record_operation_outcome(
                    operation=operation,
                    outcome=outcome,
                    job_id=job_id,
                    context={"return_code": return_code},
                )
                _log_job_event(
                    operation=operation,
                    job_id=job_id,
                    outcome=outcome,
                    level="INFO" if return_code == 0 else "ERROR",
                    summary={"return_code": return_code},
                )
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
                _log_job_event(
                    operation=operation,
                    job_id=job_id,
                    outcome="timeout",
                    level="ERROR",
                    summary={"timeout_seconds": timeout_seconds},
                )
                observability.record_job_completed(
                    operation=operation,
                    outcome="timeout",
                    duration_seconds=time.perf_counter() - started,
                )
                alerts.record_operation_outcome(
                    operation=operation,
                    outcome="timeout",
                    job_id=job_id,
                    context={"timeout_seconds": timeout_seconds},
                )
        finally:
            high_risk_operation_guard.release()

    worker_context = contextvars.copy_context()
    threading.Thread(
        target=lambda: worker_context.run(_release_when_finished),
        name=f"{operation}-guard-release",
        daemon=True,
    ).start()
    return process
