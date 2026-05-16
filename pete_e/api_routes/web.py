from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import fastapi
from fastapi import HTTPException, Request
from jinja2 import Environment, FileSystemLoader, select_autoescape

from pete_e.api_routes import dependencies
from pete_e.api_errors import get_or_create_correlation_id
from pete_e.api_routes.dependencies import current_user_from_session, require_browser_user, require_role
from pete_e.application.apple_dropbox_ingest import run_apple_health_ingest
from pete_e.application.sync import run_sync_with_retries, run_withings_only_with_retries
from pete_e.application.web_console import WebConsoleReadModel
from pete_e.cli.status import DEFAULT_TIMEOUT_SECONDS
from pete_e.config import settings
from pete_e.domain.auth import AuthUser, ROLE_OPERATOR, ROLE_OWNER, ROLE_READ_ONLY, RoleName
from pete_e.domain.daily_sync import AppleHealthIngestResult

try:  # pragma: no cover - exercised when Starlette is installed.
    from starlette.responses import JSONResponse
    from starlette.responses import HTMLResponse, RedirectResponse
except ImportError:  # pragma: no cover - keeps lightweight unit-test stubs importable.
    class JSONResponse:  # type: ignore[no-redef]
        def __init__(self, content: dict, status_code: int = 200, headers: dict[str, str] | None = None):
            self.content = content
            self.status_code = status_code
            self.headers = headers or {}

    class HTMLResponse:  # type: ignore[no-redef]
        def __init__(self, content: str = "", status_code: int = 200, headers: dict[str, str] | None = None):
            self.body = content.encode("utf-8")
            self.status_code = status_code
            self.headers = headers or {}

    class RedirectResponse(HTMLResponse):  # type: ignore[no-redef]
        def __init__(self, url: str, status_code: int = 303):
            super().__init__("", status_code=status_code, headers={"location": url})


router = fastapi.APIRouter() if hasattr(fastapi, "APIRouter") else fastapi.FastAPI()

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
COMMAND_CONFIRMATIONS = {
    "sync": "RUN SYNC",
    "withings_sync": "RUN WITHINGS SYNC",
    "apple_ingest": "RUN APPLE INGEST",
    "plan": "GENERATE PLAN",
    "message_resend": "RESEND MESSAGE",
    "deploy": "RUN DEPLOY",
}
MESSAGE_TYPES = {"summary", "trainer", "plan"}

_templates = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(("html", "xml")),
)


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    href: str
    min_role: RoleName


NAV_ITEMS: tuple[NavItem, ...] = (
    NavItem("status", "Status", "/console/status", ROLE_READ_ONLY),
    NavItem("plan", "Plan", "/console/plan", ROLE_READ_ONLY),
    NavItem("trends", "Trends", "/console/trends", ROLE_READ_ONLY),
    NavItem("nutrition", "Nutrition", "/console/nutrition", ROLE_READ_ONLY),
    NavItem("logs", "Logs", "/console/logs", ROLE_READ_ONLY),
    NavItem("jobs", "Jobs", "/console/jobs", ROLE_OPERATOR),
    NavItem("history", "History", "/console/history", ROLE_OPERATOR),
    NavItem("operations", "Operations", "/console/operations", ROLE_OPERATOR),
    NavItem("admin", "Admin", "/console/admin", ROLE_OWNER),
)

PAGE_CONTENT: dict[str, dict[str, object]] = {
    "dashboard": {
        "title": "Operator Console",
        "eyebrow": "Overview",
        "summary": "Daily operating surface.",
        "panels": [
            {"title": "Status", "body": "Health checks are ready to load."},
            {"title": "Plan", "body": "Current week plan view is ready."},
            {"title": "Nutrition", "body": "Daily nutrition summary is ready."},
        ],
    },
    "status": {
        "title": "System Status",
        "eyebrow": "Health",
        "summary": "Service health, sync freshness, and integration checks.",
        "panels": [
            {"title": "Checks", "body": "No health check results loaded."},
            {"title": "Sync Freshness", "body": "No source freshness data loaded."},
        ],
    },
    "plan": {
        "title": "Current Plan",
        "eyebrow": "Training",
        "summary": "Current week plan and planner decision trace.",
        "panels": [
            {"title": "Week Plan", "body": "No week plan loaded."},
            {"title": "Decision Trace", "body": "No decision trace loaded."},
        ],
    },
    "trends": {
        "title": "Trend Snapshots",
        "eyebrow": "Metrics",
        "summary": "Weight, sleep, HRV, and training volume.",
        "panels": [
            {"title": "Readiness", "body": "No readiness snapshot loaded."},
            {"title": "Load", "body": "No training load snapshot loaded."},
        ],
    },
    "nutrition": {
        "title": "Nutrition Summary",
        "eyebrow": "Fuel",
        "summary": "Daily macro totals and recent logs.",
        "panels": [
            {"title": "Today", "body": "No daily macro totals loaded."},
            {"title": "Recent Logs", "body": "No recent nutrition logs loaded."},
        ],
    },
    "logs": {
        "title": "Logs",
        "eyebrow": "Observability",
        "summary": "Recent application logs with request and job correlation.",
        "panels": [
            {"title": "Recent Lines", "body": "No log lines loaded."},
        ],
    },
    "jobs": {
        "title": "Jobs",
        "eyebrow": "Operations",
        "summary": "Durable command execution status.",
        "panels": [
            {"title": "Recent Jobs", "body": "No jobs have been recorded."},
        ],
    },
    "history": {
        "title": "Command History",
        "eyebrow": "Audit",
        "summary": "Searchable durable audit records for console command operations.",
        "panels": [
            {"title": "Recent Commands", "body": "No command history has been recorded."},
        ],
    },
    "operations": {
        "title": "Operations",
        "eyebrow": "Commands",
        "summary": "Confirmed workflow commands.",
        "panels": [
            {"title": "Sync", "body": "No sync command selected."},
            {"title": "Plan Generation", "body": "No plan command selected."},
        ],
    },
    "admin": {
        "title": "Admin",
        "eyebrow": "Owner",
        "summary": "User, role, and deployment-sensitive administration.",
        "panels": [
            {"title": "Users", "body": "Owner access confirmed."},
            {"title": "Security", "body": "No security event selected."},
        ],
    },
}


def _request_path(request: Request) -> str:
    scope = getattr(request, "scope", None)
    if isinstance(scope, dict) and scope.get("path"):
        return str(scope["path"])
    url = getattr(request, "url", None)
    path = getattr(url, "path", None)
    return str(path or "/console")


def _login_redirect(request: Request):
    next_path = quote(_request_path(request), safe="/")
    return RedirectResponse(f"/login?next={next_path}", status_code=303)


def _role_visible(user: AuthUser, min_role: RoleName) -> bool:
    if min_role == ROLE_READ_ONLY:
        return True
    if min_role == ROLE_OPERATOR:
        return user.can_operate
    if min_role == ROLE_OWNER:
        return user.is_owner
    return user.has_role(min_role)


def visible_nav_items(user: AuthUser) -> list[NavItem]:
    return [item for item in NAV_ITEMS if _role_visible(user, item.min_role)]


def _display_name(user: AuthUser) -> str:
    return user.display_name or user.username


def _render(template_name: str, **context):
    template = _templates.get_template(template_name)
    return HTMLResponse(template.render(**context))


def _console_read_model() -> WebConsoleReadModel:
    return WebConsoleReadModel(
        metrics_service=dependencies.get_metrics_service(),
        nutrition_service=dependencies.get_nutrition_service(),
        plan_service=dependencies.get_plan_service(),
        status_service=dependencies.get_status_service(),
    )


def _command_cards(today: date) -> list[dict[str, object]]:
    return [
        {
            "key": "sync",
            "title": "Run Sync",
            "body": "Refresh source data now.",
            "endpoint": "/console/operations/run-sync",
            "confirmation": COMMAND_CONFIRMATIONS["sync"],
            "fields": [
                {"name": "days", "label": "Days", "type": "number", "value": 3, "min": 1, "max": 30},
                {"name": "retries", "label": "Retries", "type": "number", "value": 1, "min": 0, "max": 5},
            ],
        },
        {
            "key": "withings_sync",
            "title": "Withings Sync",
            "body": "Refresh only Withings measurements and source summaries.",
            "endpoint": "/console/operations/run-withings-sync",
            "confirmation": COMMAND_CONFIRMATIONS["withings_sync"],
            "fields": [
                {"name": "days", "label": "Days", "type": "number", "value": 7, "min": 1, "max": 30},
                {"name": "retries", "label": "Retries", "type": "number", "value": 1, "min": 0, "max": 5},
            ],
        },
        {
            "key": "apple_ingest",
            "title": "Apple Ingest",
            "body": "Ingest only Apple Health exports from Dropbox.",
            "endpoint": "/console/operations/ingest-apple",
            "confirmation": COMMAND_CONFIRMATIONS["apple_ingest"],
        },
        {
            "key": "plan",
            "title": "Generate Plan",
            "body": "Start the plan generator.",
            "endpoint": "/console/operations/generate-plan",
            "confirmation": COMMAND_CONFIRMATIONS["plan"],
            "fields": [
                {"name": "start_date", "label": "Start date", "type": "date", "value": today.isoformat()},
                {"name": "weeks", "label": "Weeks", "type": "number", "value": 1, "min": 1, "max": 12},
            ],
        },
        {
            "key": "message_resend",
            "title": "Resend Message",
            "body": "Send a selected Telegram message again.",
            "endpoint": "/console/operations/resend-message",
            "confirmation": COMMAND_CONFIRMATIONS["message_resend"],
            "message_types": [
                {"value": "plan", "label": "Weekly plan"},
                {"value": "summary", "label": "Daily summary"},
                {"value": "trainer", "label": "Trainer check-in"},
            ],
        },

        {
            "key": "deploy",
            "title": "Run Deploy Script",
            "body": "Owner-only manual deploy trigger for webhook fallback.",
            "endpoint": "/console/operations/run-deploy",
            "confirmation": COMMAND_CONFIRMATIONS["deploy"],
            "requires_owner": True,
        },
    ]


def _operator_today() -> date:
    try:
        timezone = ZoneInfo(str(getattr(settings, "USER_TIMEZONE", "Europe/London")))
    except ZoneInfoNotFoundError:
        return date.today()
    return datetime.now(timezone).date()


def _payload_value(payload: dict[str, Any] | None, key: str, default: Any = None) -> Any:
    if not isinstance(payload, dict):
        return default
    value = payload.get(key)
    return default if value is None else value


def _payload_int(payload: dict[str, Any] | None, key: str, default: int, *, min_value: int, max_value: int) -> int:
    try:
        value = int(_payload_value(payload, key, default))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{key} must be an integer") from exc
    if value < min_value or value > max_value:
        raise HTTPException(status_code=400, detail=f"{key} must be between {min_value} and {max_value}")
    return value


def _query_value(request: Request, key: str, default: str = "") -> str:
    query_params = getattr(request, "query_params", {}) or {}
    getter = getattr(query_params, "get", None)
    value = getter(key, default) if callable(getter) else default
    return str(default if value is None else value)


def _query_int(request: Request, key: str, default: int, *, min_value: int, max_value: int) -> int:
    try:
        value = int(_query_value(request, key, str(default)).strip() or default)
    except (TypeError, ValueError):
        value = default
    return max(min_value, min(value, max_value))


def _require_operator_command_user(request: Request, command: str) -> AuthUser:
    try:
        return require_role(request, ROLE_OPERATOR, require_csrf=True)
    except HTTPException as exc:
        dependencies.audit_command_event(
            request,
            command=command,
            outcome="authorization_denied",
            summary={"status_code": exc.status_code},
            level="WARNING",
        )
        raise


def _require_command_confirmation(request: Request, command: str, payload: dict[str, Any] | None) -> None:
    expected = COMMAND_CONFIRMATIONS[command]
    actual = str(_payload_value(payload, "confirmation", "")).strip()
    if actual == expected:
        return

    dependencies.audit_command_event(
        request,
        command=command,
        outcome="confirmation_failed",
        summary={"expected": expected, "provided": bool(actual)},
        level="WARNING",
    )
    raise HTTPException(
        status_code=400,
        detail={
            "code": "confirmation_required",
            "message": f"Type {expected} to confirm this command.",
            "expected_confirmation": expected,
        },
    )


def _audit_command_start(request: Request, command: str, summary: dict[str, Any]) -> None:
    dependencies.audit_command_event(request, command=command, outcome="started", summary=summary)


def _audit_command_success(request: Request, command: str, summary: dict[str, Any]) -> None:
    dependencies.audit_command_event(request, command=command, outcome="succeeded", summary=summary)


def _audit_command_failure(request: Request, command: str, exc: Exception) -> None:
    status_code = getattr(exc, "status_code", 500)
    dependencies.audit_command_event(
        request,
        command=command,
        outcome="failed",
        summary={"status_code": status_code, "error": str(getattr(exc, "detail", exc))},
        level="ERROR",
    )


def _apple_ingest_source_statuses(result: AppleHealthIngestResult) -> dict[str, str]:
    statuses = dict(result.statuses or {})
    if statuses:
        return {str(source): str(status) for source, status in statuses.items()}
    return {"Apple Health": "ok" if result.success else "failed"}


def _apple_ingest_failed_sources(result: AppleHealthIngestResult) -> list[str]:
    failures = [str(source) for source in result.failures or ()]
    if failures or result.success:
        return failures
    return ["Apple Health"]


def _apple_ingest_summary(result: AppleHealthIngestResult) -> str:
    statuses = _apple_ingest_source_statuses(result)
    status_fragment = ", ".join(f"{source}={status}" for source, status in statuses.items())
    verdict = "success" if result.success else "failed"
    import_summary = result.summary
    if import_summary is None:
        return f"Apple ingest summary: result={verdict} | {status_fragment}"
    return (
        f"Apple ingest summary: result={verdict} | {status_fragment} | "
        f"files={len(import_summary.sources)} | workouts={import_summary.workouts} | "
        f"metric_points={import_summary.daily_points} | hr_days={import_summary.hr_days} | "
        f"sleep_days={import_summary.sleep_days}"
    )


def _apple_ingest_import_summary(result: AppleHealthIngestResult) -> dict[str, Any] | None:
    import_summary = result.summary
    if import_summary is None:
        return None
    return {
        "sources": list(import_summary.sources),
        "source_file_count": len(import_summary.sources),
        "workouts": import_summary.workouts,
        "daily_points": import_summary.daily_points,
        "hr_days": import_summary.hr_days,
        "sleep_days": import_summary.sleep_days,
    }


def _render_console(
    request: Request,
    page_key: str,
    *,
    min_role: RoleName = ROLE_READ_ONLY,
    template_name: str = "console/page.html",
    context_loader: Callable[[], dict[str, object]] | None = None,
    **context,
):
    try:
        user = require_browser_user(request)
    except HTTPException as exc:
        if exc.status_code == 401:
            return _login_redirect(request)
        raise

    if not _role_visible(user, min_role):
        raise HTTPException(status_code=403, detail="Insufficient role")

    if context_loader is not None:
        context.update(context_loader())

    page = PAGE_CONTENT[page_key]
    return _render(
        template_name,
        active_nav=page_key,
        nav_items=visible_nav_items(user),
        page=page,
        request_path=_request_path(request),
        user=user,
        user_display_name=_display_name(user),
        **context,
    )


@router.get("/login")
def login_page(request: Request):
    if current_user_from_session(request) is not None:
        return RedirectResponse("/console", status_code=303)
    return _render("auth/login.html", next_path=getattr(request, "query_params", {}).get("next", "/console"))


@router.get("/console")
def console_index(request: Request):
    return _render_console(request, "dashboard")


@router.get("/console/status")
def console_status(request: Request):
    return _render_console(
        request,
        "status",
        template_name="console/status.html",
        context_loader=lambda: {
            "status_view": _console_read_model().status(target_date=_operator_today(), timeout=DEFAULT_TIMEOUT_SECONDS)
        },
    )


@router.get("/console/plan")
def console_plan(request: Request):
    return _render_console(
        request,
        "plan",
        template_name="console/plan.html",
        context_loader=lambda: {"plan_view": _console_read_model().plan(target_date=_operator_today())},
    )


@router.get("/console/trends")
def console_trends(request: Request):
    return _render_console(
        request,
        "trends",
        template_name="console/trends.html",
        context_loader=lambda: {"trends_view": _console_read_model().trends(target_date=_operator_today())},
    )


@router.get("/console/nutrition")
def console_nutrition(request: Request):
    return _render_console(
        request,
        "nutrition",
        template_name="console/nutrition.html",
        context_loader=lambda: {"nutrition_view": _console_read_model().nutrition(target_date=_operator_today())},
    )


@router.get("/console/logs")
def console_logs(request: Request):
    lines = _query_int(request, "lines", 200, min_value=1, max_value=1000)
    tag = _query_value(request, "tag").strip()
    outcome = _query_value(request, "outcome").strip()
    return _render_console(
        request,
        "logs",
        template_name="console/logs.html",
        context_loader=lambda: {
            "logs_view": _console_read_model().logs(
                lines=lines,
                tag=tag or None,
                outcome=outcome or None,
            )
        },
    )


@router.get("/console/jobs")
def console_jobs(request: Request):
    limit = _query_int(request, "limit", 25, min_value=1, max_value=100)
    return _render_console(
        request,
        "jobs",
        min_role=ROLE_OPERATOR,
        template_name="console/jobs.html",
        context_loader=lambda: {
            "current_jobs": dependencies.get_job_service().list_current_jobs(limit=10),
            "jobs": dependencies.get_job_service().list_recent_jobs(limit=limit),
            "selected_job": None,
        },
    )


@router.get("/console/jobs/{job_id}")
def console_job_detail(request: Request, job_id: str):
    return _render_console(
        request,
        "jobs",
        min_role=ROLE_OPERATOR,
        template_name="console/jobs.html",
        context_loader=lambda: {
            "current_jobs": dependencies.get_job_service().list_current_jobs(limit=10),
            "jobs": dependencies.get_job_service().list_recent_jobs(limit=25),
            "selected_job": _require_job(job_id),
        },
    )


@router.get("/console/jobs/{job_id}/status")
def console_job_status(request: Request, job_id: str):
    require_role(request, ROLE_OPERATOR)
    job = _require_job(job_id)
    return JSONResponse({"job": job.to_status_payload()})


def _command_history_context(request: Request) -> dict[str, object]:
    limit = _query_int(request, "limit", 25, min_value=1, max_value=100)
    query = _query_value(request, "q").strip()
    command = _query_value(request, "command").strip()
    outcome = _query_value(request, "outcome").strip()
    entries = dependencies.get_job_service().list_command_history(
        limit=limit,
        query=query or None,
        command=command or None,
        outcome=outcome or None,
    )
    return {
        "history_entries": entries,
        "history_filters": {
            "limit": limit,
            "q": query,
            "command": command,
            "outcome": outcome,
        },
    }


@router.get("/console/history")
def console_command_history(request: Request):
    return _render_console(
        request,
        "history",
        min_role=ROLE_OPERATOR,
        template_name="console/history.html",
        context_loader=lambda: _command_history_context(request),
    )


@router.get("/console/history.json")
def console_command_history_api(request: Request):
    require_role(request, ROLE_OPERATOR)
    context = _command_history_context(request)
    entries = context["history_entries"]
    return JSONResponse(
        {
            "filters": context["history_filters"],
            "entries": [entry.to_payload() for entry in entries],
        }
    )


@router.get("/console/operations")
def console_operations(request: Request):
    return _render_console(
        request,
        "operations",
        min_role=ROLE_OPERATOR,
        template_name="console/operations.html",
        context_loader=lambda: {"command_cards": _command_cards(_operator_today())},
    )


@router.post("/console/operations/run-sync")
def console_run_sync(request: Request, payload: dict[str, Any] | None = None):
    command = "sync"
    _require_operator_command_user(request, command)
    _require_command_confirmation(request, command, payload)
    days = _payload_int(payload, "days", 3, min_value=1, max_value=30)
    retries = _payload_int(payload, "retries", 1, min_value=0, max_value=5)
    summary = {"days": days, "retries": retries}
    job_id = dependencies.prepare_job_context(request, command)
    correlation_id = get_or_create_correlation_id(request)
    requester = getattr(getattr(request, "state", None), "auth_user", None)
    _audit_command_start(request, command, summary)

    try:
        dependencies.enforce_command_rate_limit(request, command)
        result = dependencies.get_job_service().run_callback(
            job_id=job_id,
            operation=command,
            callback=lambda: run_sync_with_retries(days=days, retries=retries),
            requester=requester,
            request_id=correlation_id,
            correlation_id=correlation_id,
            request_summary=summary,
            timeout_seconds=dependencies.DEFAULT_SYNC_TIMEOUT_SECONDS,
            auth_scheme=getattr(getattr(request, "state", None), "auth_scheme", None),
            result_summary_builder=lambda sync_result: sync_result.summary_line(days=days),
        )
    except Exception as exc:
        _audit_command_failure(request, command, exc)
        raise

    payload_out = {
        "status": "completed",
        "command": command,
        "success": result.success,
        "summary": result.summary_line(days=days),
        "job_id": job_id,
        "status_url": f"/console/jobs/{job_id}",
        "attempts": result.attempts,
        "failed_sources": result.failed_sources,
        "source_statuses": result.source_statuses,
    }
    _audit_command_success(request, command, payload_out)
    return payload_out


@router.post("/console/operations/run-withings-sync")
def console_run_withings_sync(request: Request, payload: dict[str, Any] | None = None):
    command = "withings_sync"
    _require_operator_command_user(request, command)
    _require_command_confirmation(request, command, payload)
    days = _payload_int(payload, "days", 7, min_value=1, max_value=30)
    retries = _payload_int(payload, "retries", 1, min_value=0, max_value=5)
    summary = {"days": days, "retries": retries, "source": "Withings"}
    job_id = dependencies.prepare_job_context(request, command)
    correlation_id = get_or_create_correlation_id(request)
    requester = getattr(getattr(request, "state", None), "auth_user", None)
    _audit_command_start(request, command, summary)

    try:
        dependencies.enforce_command_rate_limit(request, command)
        result = dependencies.get_job_service().run_callback(
            job_id=job_id,
            operation=command,
            callback=lambda: run_withings_only_with_retries(days=days, retries=retries),
            requester=requester,
            request_id=correlation_id,
            correlation_id=correlation_id,
            request_summary=summary,
            timeout_seconds=dependencies.DEFAULT_SYNC_TIMEOUT_SECONDS,
            auth_scheme=getattr(getattr(request, "state", None), "auth_scheme", None),
            result_summary_builder=lambda sync_result: sync_result.summary_line(days=days),
        )
    except Exception as exc:
        _audit_command_failure(request, command, exc)
        raise

    payload_out = {
        "status": "completed",
        "command": command,
        "success": result.success,
        "summary": result.summary_line(days=days),
        "job_id": job_id,
        "status_url": f"/console/jobs/{job_id}",
        "attempts": result.attempts,
        "failed_sources": result.failed_sources,
        "source_statuses": result.source_statuses,
    }
    _audit_command_success(request, command, payload_out)
    return payload_out


@router.post("/console/operations/ingest-apple")
def console_ingest_apple(request: Request, payload: dict[str, Any] | None = None):
    command = "apple_ingest"
    _require_operator_command_user(request, command)
    _require_command_confirmation(request, command, payload)
    summary = {"source": "Apple Health"}
    job_id = dependencies.prepare_job_context(request, command)
    correlation_id = get_or_create_correlation_id(request)
    requester = getattr(getattr(request, "state", None), "auth_user", None)
    _audit_command_start(request, command, summary)

    try:
        dependencies.enforce_command_rate_limit(request, command)
        result = dependencies.get_job_service().run_callback(
            job_id=job_id,
            operation=command,
            callback=run_apple_health_ingest,
            requester=requester,
            request_id=correlation_id,
            correlation_id=correlation_id,
            request_summary=summary,
            timeout_seconds=dependencies.DEFAULT_SYNC_TIMEOUT_SECONDS,
            auth_scheme=getattr(getattr(request, "state", None), "auth_scheme", None),
            result_summary_builder=_apple_ingest_summary,
        )
    except Exception as exc:
        _audit_command_failure(request, command, exc)
        raise

    payload_out = {
        "status": "completed",
        "command": command,
        "success": result.success,
        "summary": _apple_ingest_summary(result),
        "job_id": job_id,
        "status_url": f"/console/jobs/{job_id}",
        "failed_sources": _apple_ingest_failed_sources(result),
        "source_statuses": _apple_ingest_source_statuses(result),
        "import_summary": _apple_ingest_import_summary(result),
    }
    _audit_command_success(request, command, payload_out)
    return payload_out


@router.post("/console/operations/generate-plan")
def console_generate_plan(request: Request, payload: dict[str, Any] | None = None):
    command = "plan"
    user = _require_operator_command_user(request, command)
    _require_command_confirmation(request, command, payload)
    weeks = _payload_int(payload, "weeks", 1, min_value=1, max_value=12)
    start_date = str(_payload_value(payload, "start_date", _operator_today().isoformat())).strip()
    try:
        date.fromisoformat(start_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="start_date must use YYYY-MM-DD") from exc

    summary = {"weeks": weeks, "start_date": start_date}
    job_id = dependencies.prepare_job_context(request, command)
    correlation_id = get_or_create_correlation_id(request)
    _audit_command_start(request, command, summary)
    try:
        dependencies.enforce_command_rate_limit(request, command)
        dependencies.get_job_service().enqueue_subprocess(
            job_id=job_id,
            operation=command,
            command=["pete", "plan", "--weeks", str(weeks), "--start-date", start_date],
            requester=user,
            request_id=correlation_id,
            correlation_id=correlation_id,
            request_summary=summary,
            timeout_seconds=dependencies.DEFAULT_PROCESS_TIMEOUT_SECONDS,
            auth_scheme=getattr(getattr(request, "state", None), "auth_scheme", None),
        )
    except Exception as exc:
        _audit_command_failure(request, command, exc)
        raise

    response = {
        "status": "queued",
        "command": command,
        "job_id": job_id,
        "status_url": f"/console/jobs/{job_id}",
        "status_api_url": f"/console/jobs/{job_id}/status",
        **summary,
    }
    _audit_command_success(request, command, response)
    return response


@router.post("/console/operations/resend-message")
def console_resend_message(request: Request, payload: dict[str, Any] | None = None):
    command = "message_resend"
    user = _require_operator_command_user(request, command)
    _require_command_confirmation(request, command, payload)
    message_type = str(_payload_value(payload, "message_type", "plan")).strip()
    if message_type not in MESSAGE_TYPES:
        raise HTTPException(status_code=400, detail="message_type must be summary, trainer, or plan")

    summary = {"message_type": message_type}
    job_id = dependencies.prepare_job_context(request, command)
    correlation_id = get_or_create_correlation_id(request)
    _audit_command_start(request, command, summary)
    try:
        dependencies.enforce_command_rate_limit(request, command)
        dependencies.get_job_service().enqueue_subprocess(
            job_id=job_id,
            operation=command,
            command=["pete", "message", f"--{message_type}", "--send"],
            requester=user,
            request_id=correlation_id,
            correlation_id=correlation_id,
            request_summary=summary,
            timeout_seconds=dependencies.DEFAULT_PROCESS_TIMEOUT_SECONDS,
            auth_scheme=getattr(getattr(request, "state", None), "auth_scheme", None),
        )
    except Exception as exc:
        _audit_command_failure(request, command, exc)
        raise

    response = {
        "status": "queued",
        "command": command,
        "job_id": job_id,
        "status_url": f"/console/jobs/{job_id}",
        "status_api_url": f"/console/jobs/{job_id}/status",
        **summary,
    }
    _audit_command_success(request, command, response)
    return response


@router.post("/console/operations/run-deploy")
def console_run_deploy(request: Request, payload: dict[str, Any] | None = None):
    command = "deploy"
    user = _require_operator_command_user(request, command)
    if not user.is_owner:
        raise HTTPException(status_code=403, detail="Deploy can only be triggered by an owner user")
    _require_command_confirmation(request, command, payload)

    summary = {"source": "web_console_owner_manual"}
    job_id = dependencies.prepare_job_context(request, command)
    correlation_id = get_or_create_correlation_id(request)
    _audit_command_start(request, command, summary)

    try:
        dependencies.enforce_command_rate_limit(request, command)
        dependencies.get_job_service().enqueue_subprocess(
            job_id=job_id,
            operation=command,
            command=[str(dependencies.configured_deploy_script_path())],
            requester=user,
            request_id=correlation_id,
            correlation_id=correlation_id,
            request_summary=summary,
            timeout_seconds=dependencies.DEFAULT_PROCESS_TIMEOUT_SECONDS,
            auth_scheme=getattr(getattr(request, "state", None), "auth_scheme", None),
        )
    except Exception as exc:
        _audit_command_failure(request, command, exc)
        raise

    response = {
        "status": "queued",
        "command": command,
        "job_id": job_id,
        "status_url": f"/console/jobs/{job_id}",
        "status_api_url": f"/console/jobs/{job_id}/status",
        **summary,
    }
    _audit_command_success(request, command, response)
    return response


@router.get("/console/admin")
def console_admin(request: Request):
    return _render_console(request, "admin", min_role=ROLE_OWNER)


def _require_job(job_id: str):
    job = dependencies.get_job_service().get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
