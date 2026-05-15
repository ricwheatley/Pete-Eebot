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
from pete_e.api_routes.dependencies import current_user_from_session, require_browser_user, require_role
from pete_e.application.sync import run_sync_with_retries
from pete_e.application.web_console import WebConsoleReadModel
from pete_e.cli.status import DEFAULT_TIMEOUT_SECONDS
from pete_e.config import settings
from pete_e.domain.auth import AuthUser, ROLE_OPERATOR, ROLE_OWNER, ROLE_READ_ONLY, RoleName

try:  # pragma: no cover - exercised when Starlette is installed.
    from starlette.responses import HTMLResponse, RedirectResponse
except ImportError:  # pragma: no cover - keeps lightweight unit-test stubs importable.
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
    "plan": "GENERATE PLAN",
    "message_resend": "RESEND MESSAGE",
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
    _audit_command_start(request, command, summary)

    try:
        dependencies.enforce_command_rate_limit(request, command)
        result = dependencies.run_guarded_high_risk_operation(
            command,
            lambda: run_sync_with_retries(days=days, retries=retries),
            timeout_seconds=dependencies.DEFAULT_SYNC_TIMEOUT_SECONDS,
            job_id=job_id,
        )
    except Exception as exc:
        _audit_command_failure(request, command, exc)
        raise

    payload_out = {
        "status": "completed",
        "command": command,
        "success": result.success,
        "summary": result.summary_line(days=days),
        "attempts": result.attempts,
        "failed_sources": result.failed_sources,
        "source_statuses": result.source_statuses,
    }
    _audit_command_success(request, command, payload_out)
    return payload_out


@router.post("/console/operations/generate-plan")
def console_generate_plan(request: Request, payload: dict[str, Any] | None = None):
    command = "plan"
    _require_operator_command_user(request, command)
    _require_command_confirmation(request, command, payload)
    weeks = _payload_int(payload, "weeks", 1, min_value=1, max_value=12)
    start_date = str(_payload_value(payload, "start_date", _operator_today().isoformat())).strip()
    try:
        date.fromisoformat(start_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="start_date must use YYYY-MM-DD") from exc

    summary = {"weeks": weeks, "start_date": start_date}
    job_id = dependencies.prepare_job_context(request, command)
    _audit_command_start(request, command, summary)
    try:
        dependencies.enforce_command_rate_limit(request, command)
        dependencies.start_guarded_high_risk_process(
            command,
            ["pete", "plan", "--weeks", str(weeks), "--start-date", start_date],
            job_id=job_id,
        )
    except Exception as exc:
        _audit_command_failure(request, command, exc)
        raise

    response = {"status": "started", "command": command, **summary}
    _audit_command_success(request, command, response)
    return response


@router.post("/console/operations/resend-message")
def console_resend_message(request: Request, payload: dict[str, Any] | None = None):
    command = "message_resend"
    _require_operator_command_user(request, command)
    _require_command_confirmation(request, command, payload)
    message_type = str(_payload_value(payload, "message_type", "plan")).strip()
    if message_type not in MESSAGE_TYPES:
        raise HTTPException(status_code=400, detail="message_type must be summary, trainer, or plan")

    summary = {"message_type": message_type}
    job_id = dependencies.prepare_job_context(request, command)
    _audit_command_start(request, command, summary)
    try:
        dependencies.enforce_command_rate_limit(request, command)
        dependencies.start_guarded_high_risk_process(
            command,
            ["pete", "message", f"--{message_type}", "--send"],
            job_id=job_id,
        )
    except Exception as exc:
        _audit_command_failure(request, command, exc)
        raise

    response = {"status": "started", "command": command, **summary}
    _audit_command_success(request, command, response)
    return response


@router.get("/console/admin")
def console_admin(request: Request):
    return _render_console(request, "admin", min_role=ROLE_OWNER)
