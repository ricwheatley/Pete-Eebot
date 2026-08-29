from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re
import sys
from typing import Any, Callable
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import fastapi
from fastapi import HTTPException, Request
from jinja2 import Environment, PackageLoader, select_autoescape
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from pete_e.api_routes import dependencies
from pete_e.api_errors import get_or_create_correlation_id
from pete_e.api_routes.dependencies import current_user_from_session, require_browser_user, require_role
from pete_e.application.exceptions import ApplicationError
from pete_e.application.apple_dropbox_ingest import run_apple_health_ingest
from pete_e.application.morning_report import MorningReportResult
from pete_e.application.plan_duration import (
    DEFAULT_PLAN_WEEKS,
    PLAN_DURATION_HELP,
    SUPPORTED_PLAN_WEEKS,
    validate_plan_weeks,
)
from pete_e.application.sync import run_sync_with_retries, run_withings_only_with_retries
from pete_e.application.web_console import WebConsoleReadModel
from pete_e.application.wger_week_replacement import run_wger_week_replacement
from pete_e.cli.status import DEFAULT_TIMEOUT_SECONDS
from pete_e.config import settings
from pete_e.domain.auth import AuthenticatedPrincipal, AuthUser, ROLE_OPERATOR, ROLE_OWNER, ROLE_READ_ONLY, RoleName
from pete_e.domain.daily_sync import AppleHealthIngestResult
from pete_e.package_resources import package_resource, package_resource_directory

router = fastapi.APIRouter()

TEMPLATE_DIR = package_resource("templates")
STATIC_DIR = package_resource_directory("static")
COMMAND_CONFIRMATIONS = {
    "sync": "RUN SYNC",
    "withings_sync": "RUN WITHINGS SYNC",
    "apple_ingest": "RUN APPLE INGEST",
    "wger_week_replace": "REPLACE WGER WEEK",
    "plan": "GENERATE PLAN",
    "message_resend": "RESEND MESSAGE",
    "morning_report_send": "SEND MORNING REPORT",
    "sunday_review": "RUN SUNDAY REVIEW",
    "lets_begin": "BEGIN STRENGTH TEST",
    "deploy": "RUN DEPLOY",
}
MESSAGE_TYPES = {"summary", "trainer", "plan"}
MESSAGE_TYPE_LABELS = {
    "summary": "Daily summary",
    "trainer": "Trainer check-in",
    "plan": "Weekly plan",
}
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LOGIN_CREDENTIAL_QUERY_KEYS = {
    "email",
    "login",
    "mfa_code",
    "password",
    "recovery_code",
    "totp_code",
    "username",
}


def _display_datetime(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")

    text = str(value).strip()
    if not text:
        return default
    if _DATE_ONLY_RE.fullmatch(text):
        try:
            return date.fromisoformat(text).strftime("%d/%m/%Y")
        except ValueError:
            return text

    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return text
    return parsed.strftime("%d/%m/%Y %H:%M:%S")


def _safe_next_path(value: Any) -> str:
    text = str(value or "/console").strip() or "/console"
    if not text.startswith("/") or text.startswith("//"):
        return "/console"
    return text
    """Perform safe next path."""

_templates = Environment(
    loader=PackageLoader("pete_e", "templates"),
    autoescape=select_autoescape(("html", "xml")),
)
_templates.filters["display_datetime"] = _display_datetime


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    href: str
    min_role: RoleName


@dataclass(frozen=True)
class ConsoleMessagePreviewResult:
    message_type: str
    message: str
    success: bool = True

    def summary_line(self) -> str:
        label = MESSAGE_TYPE_LABELS.get(self.message_type, self.message_type)
        if not self.message.strip():
            return f"No {label.lower()} message is available."
        return f"{label} preview generated."


NAV_ITEMS: tuple[NavItem, ...] = (
    NavItem("status", "Status", "/console/status", ROLE_OPERATOR),
    NavItem("plan", "Plan", "/console/plan", ROLE_READ_ONLY),
    NavItem("trends", "Trends", "/console/trends", ROLE_READ_ONLY),
    NavItem("nutrition", "Nutrition", "/console/nutrition", ROLE_READ_ONLY),
    NavItem("logs", "Logs", "/console/logs", ROLE_READ_ONLY),
    NavItem("alerts", "Alerts", "/console/alerts", ROLE_OPERATOR),
    NavItem("scheduler", "Scheduler", "/console/scheduler", ROLE_OPERATOR),
    NavItem("jobs", "Jobs", "/console/jobs", ROLE_OPERATOR),
    NavItem("history", "History", "/console/history", ROLE_OPERATOR),
    NavItem("operations", "Operations", "/console/operations", ROLE_OPERATOR),
    NavItem("security", "Security", "/console/security", ROLE_OPERATOR),
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
    "alerts": {
        "title": "Alerts",
        "eyebrow": "Operations",
        "summary": "Active and recent operational alerts.",
        "panels": [
            {"title": "Active Alerts", "body": "No active alerts observed."},
            {"title": "Recent Alerts", "body": "No alert history observed."},
        ],
    },
    "scheduler": {
        "title": "Scheduler Status",
        "eyebrow": "Operations",
        "summary": "Expected cron schedule and repair references.",
        "panels": [
            {"title": "Cron", "body": "No schedule loaded."},
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
        "summary": "Owner-managed users and browser roles.",
        "panels": [
            {"title": "Users", "body": "No users loaded."},
            {"title": "Security", "body": "No security event selected."},
        ],
    },
    "security": {
        "title": "Security",
        "eyebrow": "MFA",
        "summary": "Browser MFA enrollment for owner/operator users.",
        "panels": [
            {"title": "MFA", "body": "No MFA state loaded."},
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


BREAK_GLASS_LINKS = (
    {
        "label": "OAuth recovery",
        "href": "/docs/runtime_deploy_runbook.md#withings-oauth-and-token-recovery",
        "summary": "Provider reauthorization and token refresh steps.",
    },
    {
        "label": "Backup and restore",
        "href": "/docs/runtime_deploy_runbook.md#52-backup-and-restore",
        "summary": "Database backup and restore procedure.",
    },
    {
        "label": "Migrations",
        "href": "/docs/runtime_deploy_runbook.md#14-db-migration-path",
        "summary": "Manual schema and migration application flow.",
    },
    {
        "label": "Cron repair",
        "href": "/docs/runtime_deploy_runbook.md#33-cron-renderinstall",
        "summary": "Regenerate and activate the expected crontab.",
    },
    {
        "label": "Service restart",
        "href": "/docs/runtime_deploy_runbook.md#34-heartbeat-service-check-ad-hoc",
        "summary": "Systemd service health and restart checks.",
    },
)


def _operator_reference_links(user: AuthUser) -> tuple[dict[str, str], ...]:
    return BREAK_GLASS_LINKS if user.can_operate else ()


def _command_cards(today: date) -> list[dict[str, object]]:
    current_week_start = today - timedelta(days=today.weekday())
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
            "key": "wger_week_replace",
            "title": "Delete and Resend wger Week",
            "body": (
                "Repair a corrupted wger workout week from the existing stored plan. "
                "This deletes matching wger routine days only if present, then resends them; "
                "it never regenerates, replaces, or adjusts the Pete-E plan."
            ),
            "endpoint": "/console/operations/replace-wger-week",
            "confirmation": COMMAND_CONFIRMATIONS["wger_week_replace"],
            "fields": [
                {
                    "name": "week_start",
                    "label": "Week starting (Monday)",
                    "type": "date",
                    "value": current_week_start.isoformat(),
                    "required": True,
                    "help": "The date must match an existing stored plan week exactly.",
                },
            ],
        },
        {
            "key": "plan",
            "title": "Generate Plan",
            "body": "Create and export the next fixed 4-week 5/3/1 block.",
            "endpoint": "/console/operations/generate-plan",
            "confirmation": COMMAND_CONFIRMATIONS["plan"],
            "fields": [
                {"name": "start_date", "label": "Start date", "type": "date", "value": today.isoformat()},
                {
                    "name": "weeks",
                    "label": "Plan length (weeks)",
                    "type": "number",
                    "value": DEFAULT_PLAN_WEEKS,
                    "min": min(SUPPORTED_PLAN_WEEKS),
                    "max": max(SUPPORTED_PLAN_WEEKS),
                    "readonly": True,
                    "help": PLAN_DURATION_HELP,
                },
            ],
        },
        {
            "key": "sunday_review",
            "title": "Run Sunday Review",
            "body": "Run the weekly review automation.",
            "endpoint": "/console/operations/run-sunday-review",
            "confirmation": COMMAND_CONFIRMATIONS["sunday_review"],
        },
        {
            "key": "lets_begin",
            "title": "Start Strength Test Week",
            "body": "Create and export the one-week strength-test plan.",
            "endpoint": "/console/operations/lets-begin",
            "confirmation": COMMAND_CONFIRMATIONS["lets_begin"],
            "fields": [
                {
                    "name": "start_date",
                    "label": "Start date",
                    "type": "date",
                    "value": today.isoformat(),
                    "required": True,
                },
                {
                    "name": "start_date_confirmation",
                    "label": "Confirm start date",
                    "type": "text",
                    "value": "",
                    "placeholder": today.isoformat(),
                    "required": True,
                    "help": "Type the same YYYY-MM-DD date before starting the strength-test week.",
                },
            ],
        },
        {
            "key": "message_preview",
            "title": "Preview Message",
            "body": "Generate a Telegram message preview without sending it.",
            "endpoint": "/console/operations/preview-message",
            "button_class": "primary-button",
            "message_types": [
                {"value": "plan", "label": "Weekly plan"},
                {"value": "summary", "label": "Daily summary"},
                {"value": "trainer", "label": "Trainer check-in"},
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
            "key": "morning_report_preview",
            "title": "Preview Morning Report",
            "body": "Generate the current morning report without sending it.",
            "endpoint": "/console/operations/morning-report-preview",
            "button_class": "primary-button",
            "fields": [
                {
                    "name": "target_date",
                    "label": "Date override",
                    "type": "date",
                    "value": "",
                },
            ],
        },
        {
            "key": "morning_report_send",
            "title": "Send Morning Report",
            "body": "Generate and send the morning report via Telegram.",
            "endpoint": "/console/operations/morning-report-send",
            "confirmation": COMMAND_CONFIRMATIONS["morning_report_send"],
            "fields": [
                {
                    "name": "target_date",
                    "label": "Date override",
                    "type": "date",
                    "value": "",
                },
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


def _clean_form_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in (payload or {}).items():
        if value == "":
            continue
        cleaned[str(key)] = value
    return cleaned


def _selected_roles(payload: dict[str, Any] | None) -> tuple[str, ...]:
    raw = _payload_value(payload, "roles", ())
    if isinstance(raw, str):
        roles = tuple(part.strip() for part in raw.split(",") if part.strip())
    elif isinstance(raw, (list, tuple, set)):
        roles = tuple(str(part).strip() for part in raw if str(part).strip())
    else:
        roles = ()
    return roles or (ROLE_READ_ONLY,)


def _payload_optional_date(payload: dict[str, Any] | None, key: str) -> date | None:
    raw_value = str(_payload_value(payload, key, "") or "").strip()
    if not raw_value:
        return None
    return _parse_payload_date(raw_value, key)


def _payload_required_date(
    payload: dict[str, Any] | None,
    key: str,
    *,
    job_id: str | None = None,
    request_id: str | None = None,
) -> date:
    raw_value = str(_payload_value(payload, key, "") or "").strip()
    if raw_value:
        return _parse_payload_date(raw_value, key, job_id=job_id, request_id=request_id)
    detail: dict[str, Any] = {
        "code": "invalid_date",
        "message": f"{key} must use YYYY-MM-DD",
        "field": key,
    }
    if job_id:
        detail["job_id"] = job_id
    if request_id:
        detail["request_id"] = request_id
    raise HTTPException(status_code=400, detail=detail)


def _parse_payload_date(
    raw_value: str,
    key: str,
    *,
    job_id: str | None = None,
    request_id: str | None = None,
) -> date:
    try:
        return date.fromisoformat(raw_value)
    except ValueError as exc:
        detail: dict[str, Any] = {
            "code": "invalid_date",
            "message": f"{key} must use YYYY-MM-DD",
            "field": key,
        }
        if job_id:
            detail["job_id"] = job_id
        if request_id:
            detail["request_id"] = request_id
        raise HTTPException(
            status_code=400,
            detail=detail,
        ) from exc


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


def _require_start_date_confirmation(
    request: Request,
    command: str,
    payload: dict[str, Any] | None,
    start_date: date,
    *,
    job_id: str | None = None,
    request_id: str | None = None,
) -> None:
    expected = start_date.isoformat()
    actual = str(_payload_value(payload, "start_date_confirmation", "")).strip()
    if actual == expected:
        return

    dependencies.audit_command_event(
        request,
        command=command,
        outcome="confirmation_failed",
        summary={"field": "start_date_confirmation", "expected_start_date": expected, "provided": bool(actual)},
        level="WARNING",
    )
    detail: dict[str, Any] = {
        "code": "start_date_confirmation_required",
        "message": f"Type {expected} in Confirm start date before starting this command.",
        "expected_start_date": expected,
        "field": "start_date_confirmation",
    }
    if job_id:
        detail["job_id"] = job_id
    if request_id:
        detail["request_id"] = request_id
    raise HTTPException(status_code=400, detail=detail)


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


def _morning_report_result_summary(result: MorningReportResult) -> str:
    return result.summary_line()


def _build_console_message_orchestrator():
    from pete_e.application.orchestrator import Orchestrator

    return Orchestrator()


def _build_console_message_text(message_type: str, *, orchestrator=None) -> str:
    from pete_e.cli.messenger import build_daily_summary, build_trainer_summary, build_weekly_plan_overview

    orch = orchestrator or _build_console_message_orchestrator()
    if message_type == "summary":
        value = build_daily_summary(orchestrator=orch)
    elif message_type == "trainer":
        value = build_trainer_summary(orchestrator=orch)
    elif message_type == "plan":
        value = build_weekly_plan_overview(orchestrator=orch)
    else:
        raise HTTPException(status_code=400, detail="message_type must be summary, trainer, or plan")
    return "" if value is None else str(value)


def _generate_console_message_preview(message_type: str) -> ConsoleMessagePreviewResult:
    orchestrator = _build_console_message_orchestrator()
    return ConsoleMessagePreviewResult(
        message_type=message_type,
        message=_build_console_message_text(message_type, orchestrator=orchestrator),
    )


def _console_message_preview_summary(result: ConsoleMessagePreviewResult) -> str:
    return result.summary_line()


def _morning_report_failure(
    *,
    exc: Exception,
    job_id: str,
    request_id: str,
    default_code: str,
    default_message: str,
) -> HTTPException:
    if isinstance(exc, HTTPException):
        status_code = exc.status_code
        detail = exc.detail
        if isinstance(detail, dict):
            enriched = {**detail, "job_id": job_id, "request_id": request_id}
        else:
            enriched = {
                "code": default_code,
                "message": str(detail or default_message),
                "job_id": job_id,
                "request_id": request_id,
            }
        return HTTPException(status_code=status_code, detail=enriched)

    message = str(exc).strip() or default_message
    return HTTPException(
        status_code=500,
        detail={
            "code": default_code,
            "message": message,
            "job_id": job_id,
            "request_id": request_id,
        },
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
    verdict = (
        "success"
        if result.success
        else "partial"
        if "partial" in statuses.values()
        else "failed"
    )
    import_summary = result.summary
    if import_summary is None:
        return f"Apple ingest summary: result={verdict} | {status_fragment}"
    return (
        f"Apple ingest summary: result={verdict} | {status_fragment} | "
        f"files={len(import_summary.sources)} | workouts={import_summary.workouts} | "
        f"metric_points={import_summary.daily_points} | hr_days={import_summary.hr_days} | "
        f"sleep_days={import_summary.sleep_days} | failures={len(result.failure_details)}"
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


def _apple_ingest_failure_details(result: AppleHealthIngestResult) -> list[dict[str, Any]]:
    return [
        {
            "stage": failure.stage,
            "reason": failure.reason,
            "file_path": failure.file_path,
            "modified_at": failure.modified_at.isoformat() if failure.modified_at else None,
        }
        for failure in result.failure_details
    ]


def _render_console(
    request: Request,
    page_key: str,
    *,
    min_role: RoleName = ROLE_READ_ONLY,
    template_name: str = "console/page.html",
    context_loader: Callable[[AuthUser], dict[str, object]] | None = None,
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
        context.update(context_loader(user))

    page = PAGE_CONTENT[page_key]
    return _render(
        template_name,
        active_nav=page_key,
        nav_items=visible_nav_items(user),
        page=page,
        request_path=_request_path(request),
        user=user,
        user_display_name=_display_name(user),
        break_glass_links=_operator_reference_links(user),
        **context,
    )


@router.get("/login")
def login_page(request: Request):
    if current_user_from_session(request) is not None:
        return RedirectResponse("/console", status_code=303)
    query_params = getattr(request, "query_params", {}) or {}
    next_path = _safe_next_path(query_params.get("next", "/console"))
    if any(key in query_params for key in _LOGIN_CREDENTIAL_QUERY_KEYS):
        return RedirectResponse(f"/login?next={quote(next_path, safe='/')}", status_code=303)
    return _render("auth/login.html", next_path=next_path)


@router.get("/console")
def console_index(request: Request):
    return _render_console(request, "dashboard")


@router.get("/console/status")
def console_status(request: Request):
    def status_context(user: AuthUser) -> dict[str, object]:
        dependencies.enforce_command_rate_limit(request, "deep_status")
        return {
            "status_view": _console_read_model().status(
                target_date=_operator_today(),
                timeout=DEFAULT_TIMEOUT_SECONDS,
                principal=AuthenticatedPrincipal.for_user(user),
            )
        }

    return _render_console(
        request,
        "status",
        min_role=ROLE_OPERATOR,
        template_name="console/status.html",
        context_loader=status_context,
    )


@router.get("/console/plan")
def console_plan(request: Request):
    week_view = _query_value(request, "week", "current").strip().lower()
    if week_view not in {"current", "next"}:
        week_view = "current"
    return _render_console(
        request,
        "plan",
        template_name="console/plan.html",
        context_loader=lambda _user: {
            "plan_view": _console_read_model().plan(target_date=_operator_today(), week_view=week_view)
        },
    )


@router.get("/console/trends")
def console_trends(request: Request):
    return _render_console(
        request,
        "trends",
        template_name="console/trends.html",
        context_loader=lambda user: {
            "trends_view": _console_read_model().trends(
                target_date=_operator_today(),
                principal=AuthenticatedPrincipal.for_user(user),
            )
        },
    )


@router.get("/console/nutrition")
def console_nutrition(request: Request):
    return _render_console(
        request,
        "nutrition",
        template_name="console/nutrition.html",
        context_loader=lambda _user: {
            "nutrition_view": _console_read_model().nutrition(target_date=_operator_today())
        },
    )


@router.post("/console/nutrition/logs")
def console_create_nutrition_log(request: Request, payload: dict[str, Any] | None = None):
    command = "nutrition_log_create"
    user = _require_operator_command_user(request, command)
    cleaned = _clean_form_payload(payload)
    try:
        dependencies.enforce_command_rate_limit(request, command)
        log = dependencies.get_nutrition_service().log_macros(cleaned)
        local_date = str(log.get("local_date") or _operator_today().isoformat())[:10]
        summary = dependencies.get_nutrition_service().daily_summary(local_date)
    except ApplicationError as exc:
        _audit_command_failure(request, command, exc)
        raise HTTPException(status_code=exc.http_status, detail={"code": exc.code, "message": exc.message}) from exc
    response = {"success": True, "command": command, "summary": "Nutrition log saved.", "log": log, "daily_summary": summary}
    _audit_command_success(request, command, {"log_id": log.get("id"), "local_date": log.get("local_date"), "user_id": user.id})
    return response


@router.post("/console/nutrition/logs/{log_id}")
def console_update_nutrition_log(log_id: int, request: Request, payload: dict[str, Any] | None = None):
    command = "nutrition_log_update"
    user = _require_operator_command_user(request, command)
    cleaned = _clean_form_payload(payload)
    try:
        dependencies.enforce_command_rate_limit(request, command)
        log = dependencies.get_nutrition_service().update_log(log_id, cleaned)
        local_date = str(log.get("local_date") or _operator_today().isoformat())[:10]
        summary = dependencies.get_nutrition_service().daily_summary(local_date)
    except ApplicationError as exc:
        _audit_command_failure(request, command, exc)
        raise HTTPException(status_code=exc.http_status, detail={"code": exc.code, "message": exc.message}) from exc
    response = {"success": True, "command": command, "summary": "Nutrition log updated.", "log": log, "daily_summary": summary}
    _audit_command_success(request, command, {"log_id": log.get("id"), "local_date": log.get("local_date"), "user_id": user.id})
    return response


@router.get("/console/alerts")
def console_alerts(request: Request):
    severity = _query_value(request, "severity").strip()
    alert_type = _query_value(request, "type").strip()
    return _render_console(
        request,
        "alerts",
        min_role=ROLE_OPERATOR,
        template_name="console/alerts.html",
        context_loader=lambda _user: {
            "alerts_view": _console_read_model().alerts(
                severity=severity or None,
                alert_type=alert_type or None,
            )
        },
    )


@router.get("/console/scheduler")
def console_scheduler(request: Request):
    return _render_console(
        request,
        "scheduler",
        min_role=ROLE_OPERATOR,
        template_name="console/scheduler.html",
        context_loader=lambda _user: {"scheduler_view": _console_read_model().scheduler()},
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
        context_loader=lambda _user: {
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
        context_loader=lambda _user: {
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
        context_loader=lambda _user: {
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
        context_loader=lambda _user: _command_history_context(request),
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
        context_loader=lambda _user: {"command_cards": _command_cards(_operator_today())},
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
        "failure_details": _apple_ingest_failure_details(result),
        "alerts": list(result.alerts),
    }
    _audit_command_success(request, command, payload_out)
    return payload_out


@router.post("/console/operations/replace-wger-week")
def console_replace_wger_week(request: Request, payload: dict[str, Any] | None = None):
    command = "wger_week_replace"
    user = _require_operator_command_user(request, command)
    _require_command_confirmation(request, command, payload)
    week_start = _payload_required_date(payload, "week_start")
    if week_start.weekday() != 0:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_week_start",
                "message": "week_start must be a Monday.",
                "field": "week_start",
            },
        )

    summary = {
        "week_start": week_start.isoformat(),
        "source": "stored_plan_week",
        "plan_mutation": False,
    }
    job_id = dependencies.prepare_job_context(request, command)
    correlation_id = get_or_create_correlation_id(request)
    _audit_command_start(request, command, summary)
    try:
        dependencies.enforce_command_rate_limit(request, command)
        dependencies.get_job_service().enqueue_callback(
            job_id=job_id,
            operation=command,
            callback=lambda: run_wger_week_replacement(week_start=week_start),
            requester=user,
            request_id=correlation_id,
            correlation_id=correlation_id,
            request_summary=summary,
            timeout_seconds=dependencies.DEFAULT_PROCESS_TIMEOUT_SECONDS,
            auth_scheme=getattr(getattr(request, "state", None), "auth_scheme", None),
            result_summary_builder=lambda result: result.summary_line(),
        )
    except Exception as exc:
        _audit_command_failure(request, command, exc)
        raise

    response = {
        "status": "queued",
        "command": command,
        "success": True,
        "summary": (
            f"wger week replacement queued for {week_start.isoformat()} from the stored plan."
        ),
        "job_id": job_id,
        "request_id": correlation_id,
        "status_url": f"/console/jobs/{job_id}",
        "status_api_url": f"/console/jobs/{job_id}/status",
        **summary,
    }
    _audit_command_success(request, command, response)
    return response


@router.post("/console/operations/generate-plan")
def console_generate_plan(request: Request, payload: dict[str, Any] | None = None):
    command = "plan"
    user = _require_operator_command_user(request, command)
    _require_command_confirmation(request, command, payload)
    raw_weeks = _payload_value(payload, "weeks", DEFAULT_PLAN_WEEKS)
    try:
        if isinstance(raw_weeks, bool) or not isinstance(raw_weeks, (int, str)):
            raise ValueError
        requested_weeks = int(raw_weeks)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="weeks must be an integer") from exc
    weeks = validate_plan_weeks(requested_weeks)
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
            command=dependencies.pete_cli_command("plan", "--weeks", str(weeks), "--start-date", start_date),
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


@router.post("/console/operations/run-sunday-review")
def console_run_sunday_review(request: Request, payload: dict[str, Any] | None = None):
    command = "sunday_review"
    user = _require_operator_command_user(request, command)
    _require_command_confirmation(request, command, payload)

    summary = {"workflow": "scripts.run_sunday_review"}
    job_id = dependencies.prepare_job_context(request, command)
    correlation_id = get_or_create_correlation_id(request)
    _audit_command_start(request, command, summary)
    try:
        dependencies.enforce_command_rate_limit(request, command)
        dependencies.get_job_service().enqueue_subprocess(
            job_id=job_id,
            operation=command,
            command=[sys.executable, "-m", "scripts.run_sunday_review"],
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


@router.post("/console/operations/lets-begin")
def console_lets_begin(request: Request, payload: dict[str, Any] | None = None):
    command = "lets_begin"
    user = _require_operator_command_user(request, command)
    _require_command_confirmation(request, command, payload)
    job_id = dependencies.prepare_job_context(request, command)
    correlation_id = get_or_create_correlation_id(request)

    try:
        start_date = _payload_required_date(payload, "start_date", job_id=job_id, request_id=correlation_id)
    except Exception as exc:
        _audit_command_failure(request, command, exc)
        raise
    _require_start_date_confirmation(
        request,
        command,
        payload,
        start_date,
        job_id=job_id,
        request_id=correlation_id,
    )

    start_date_text = start_date.isoformat()
    summary = {"workflow": "pete lets-begin", "start_date": start_date_text}
    _audit_command_start(request, command, summary)
    try:
        dependencies.enforce_command_rate_limit(request, command)
        dependencies.get_job_service().enqueue_subprocess(
            job_id=job_id,
            operation=command,
            command=dependencies.pete_cli_command("lets-begin", "--start-date", start_date_text),
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


@router.get("/console/security")
def console_security(request: Request):
    return _render_console(
        request,
        "security",
        min_role=ROLE_OPERATOR,
        template_name="console/security.html",
    )


@router.post("/console/security/mfa/start")
def console_mfa_start(request: Request, payload: dict[str, Any] | None = None):
    command = "mfa_start"
    user = _require_operator_command_user(request, command)
    try:
        result = dependencies.get_user_service().start_mfa_enrollment(user)
    except ApplicationError as exc:
        _audit_command_failure(request, command, exc)
        raise HTTPException(status_code=exc.http_status, detail={"code": exc.code, "message": exc.message}) from exc
    _audit_command_success(request, command, {"target_user_id": user.id})
    return {
        "success": True,
        "command": command,
        "summary": "MFA enrollment started. Add the secret to an authenticator app, then confirm a 6-digit code.",
        "secret": result["secret"],
        "otp_uri": result["otp_uri"],
        "recovery_codes": result["recovery_codes"],
    }


@router.post("/console/security/mfa/confirm")
def console_mfa_confirm(request: Request, payload: dict[str, Any] | None = None):
    command = "mfa_confirm"
    user = _require_operator_command_user(request, command)
    code = str(_payload_value(payload, "code", "") or "").strip()
    try:
        updated = dependencies.get_user_service().confirm_mfa_enrollment(user, code)
    except ApplicationError as exc:
        _audit_command_failure(request, command, exc)
        raise HTTPException(status_code=exc.http_status, detail={"code": exc.code, "message": exc.message}) from exc
    _audit_command_success(request, command, {"target_user_id": updated.id})
    return {"success": True, "command": command, "summary": "MFA enabled.", "mfa_enabled": updated.mfa_enabled}


@router.post("/console/operations/preview-message")
def console_preview_message(request: Request, payload: dict[str, Any] | None = None):
    command = "message_preview"
    user = _require_operator_command_user(request, command)
    message_type = str(_payload_value(payload, "message_type", "plan")).strip()
    if message_type not in MESSAGE_TYPES:
        raise HTTPException(status_code=400, detail="message_type must be summary, trainer, or plan")

    summary = {"message_type": message_type, "send": False}
    job_id = dependencies.prepare_job_context(request, command)
    correlation_id = get_or_create_correlation_id(request)
    _audit_command_start(request, command, summary)
    try:
        dependencies.enforce_command_rate_limit(request, command)
        dependencies.get_job_service().enqueue_callback(
            job_id=job_id,
            operation=command,
            callback=lambda: _generate_console_message_preview(message_type),
            requester=user,
            request_id=correlation_id,
            correlation_id=correlation_id,
            request_summary=summary,
            timeout_seconds=dependencies.DEFAULT_PROCESS_TIMEOUT_SECONDS,
            auth_scheme=getattr(getattr(request, "state", None), "auth_scheme", None),
            result_summary_builder=_console_message_preview_summary,
            result_output_builder=lambda result: result.message,
        )
    except Exception as exc:
        _audit_command_failure(request, command, exc)
        raise

    response = {
        "status": "queued",
        "command": command,
        "success": True,
        "summary": "Message preview queued.",
        "message_type": message_type,
        "job_id": job_id,
        "request_id": correlation_id,
        "status_url": f"/console/jobs/{job_id}",
        "status_api_url": f"/console/jobs/{job_id}/status",
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
            command=dependencies.pete_cli_command("message", f"--{message_type}", "--send"),
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


def _run_morning_report_command(
    request: Request,
    payload: dict[str, Any] | None,
    *,
    command: str,
    user: AuthUser,
    send: bool,
    default_code: str,
    default_message: str,
) -> dict[str, Any]:
    job_id = dependencies.prepare_job_context(request, command)
    correlation_id = get_or_create_correlation_id(request)

    try:
        target_date = _payload_optional_date(payload, "target_date")
        summary = {
            "target_date": target_date.isoformat() if target_date else None,
            "send": send,
        }
        _audit_command_start(request, command, summary)
        dependencies.enforce_command_rate_limit(request, command)
        result = dependencies.get_job_service().run_callback(
            job_id=job_id,
            operation=command,
            callback=lambda: dependencies.get_morning_report_operation().execute(
                target_date=target_date,
                send=send,
            ),
            requester=user,
            request_id=correlation_id,
            correlation_id=correlation_id,
            request_summary=summary,
            timeout_seconds=dependencies.DEFAULT_PROCESS_TIMEOUT_SECONDS,
            auth_scheme=getattr(getattr(request, "state", None), "auth_scheme", None),
            result_summary_builder=_morning_report_result_summary,
        )
    except Exception as exc:
        _audit_command_failure(request, command, exc)
        raise _morning_report_failure(
            exc=exc,
            job_id=job_id,
            request_id=correlation_id,
            default_code=default_code,
            default_message=default_message,
        ) from exc

    response = {
        "status": "completed",
        "command": command,
        "success": result.success,
        "summary": result.summary_line(),
        "report": result.report,
        "sent": result.sent,
        "target_date": result.target_date,
        "job_id": job_id,
        "request_id": correlation_id,
        "status_url": f"/console/jobs/{job_id}",
    }
    _audit_command_success(request, command, response)
    return response


@router.post("/console/operations/morning-report-preview")
def console_preview_morning_report(request: Request, payload: dict[str, Any] | None = None):
    command = "morning_report_preview"
    user = _require_operator_command_user(request, command)
    return _run_morning_report_command(
        request,
        payload,
        command=command,
        user=user,
        send=False,
        default_code="morning_report_preview_failed",
        default_message="Morning report preview failed.",
    )


@router.post("/console/operations/morning-report-send")
def console_send_morning_report(request: Request, payload: dict[str, Any] | None = None):
    command = "morning_report_send"
    user = _require_operator_command_user(request, command)
    _require_command_confirmation(request, command, payload)
    return _run_morning_report_command(
        request,
        payload,
        command=command,
        user=user,
        send=True,
        default_code="morning_report_send_failed",
        default_message="Morning report send failed.",
    )


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
        dependencies.get_job_service().dispatch_external(
            job_id=job_id,
            operation=command,
            dispatch_command=dependencies.configured_deploy_dispatch_command(job_id),
            requester=user,
            request_id=correlation_id,
            correlation_id=correlation_id,
            request_summary=summary,
            auth_scheme=getattr(getattr(request, "state", None), "auth_scheme", None),
            dispatch_timeout_seconds=dependencies.settings.PETEEEBOT_DEPLOY_DISPATCH_TIMEOUT_SECONDS,
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
    return _render_console(
        request,
        "admin",
        min_role=ROLE_OWNER,
        template_name="console/admin.html",
        context_loader=lambda _user: {"users": _admin_users()},
    )


def _admin_users() -> list[AuthUser]:
    service = dependencies.get_user_service()
    loader = getattr(service, "list_users", None)
    if callable(loader):
        return list(loader())
    current = getattr(service, "user", None)
    return [current] if isinstance(current, AuthUser) else []


def _require_owner_command_user(request: Request, command: str) -> AuthUser:
    try:
        return require_role(request, ROLE_OWNER, require_csrf=True)
    except HTTPException as exc:
        dependencies.audit_command_event(
            request,
            command=command,
            outcome="authorization_denied",
            summary={"status_code": exc.status_code},
            level="WARNING",
        )
        raise


@router.post("/console/admin/users")
def console_admin_create_user(request: Request, payload: dict[str, Any] | None = None):
    command = "admin_create_user"
    owner = _require_owner_command_user(request, command)
    cleaned = _clean_form_payload(payload)
    try:
        user = dependencies.get_user_service().create_user(
            username=str(cleaned.get("username") or ""),
            email=str(cleaned.get("email")) if cleaned.get("email") else None,
            display_name=str(cleaned.get("display_name")) if cleaned.get("display_name") else None,
            password=str(cleaned.get("password") or ""),
            roles=_selected_roles(cleaned),
        )
    except ApplicationError as exc:
        _audit_command_failure(request, command, exc)
        raise HTTPException(status_code=exc.http_status, detail={"code": exc.code, "message": exc.message}) from exc
    _audit_command_success(
        request,
        command,
        {"target_user_id": user.id, "target_username": user.username, "roles": list(user.roles), "owner_user_id": owner.id},
    )
    return {"success": True, "command": command, "summary": "User created.", "user": _auth_user_payload(user)}


@router.post("/console/admin/users/{user_id}/roles")
def console_admin_update_roles(user_id: int, request: Request, payload: dict[str, Any] | None = None):
    command = "admin_update_roles"
    owner = _require_owner_command_user(request, command)
    try:
        user = dependencies.get_user_service().set_user_roles(user_id=user_id, roles=_selected_roles(payload))
    except ApplicationError as exc:
        _audit_command_failure(request, command, exc)
        raise HTTPException(status_code=exc.http_status, detail={"code": exc.code, "message": exc.message}) from exc
    _audit_command_success(
        request,
        command,
        {"target_user_id": user.id, "target_username": user.username, "roles": list(user.roles), "owner_user_id": owner.id},
    )
    return {"success": True, "command": command, "summary": "Roles updated.", "user": _auth_user_payload(user)}


@router.post("/console/admin/users/{user_id}/deactivate")
def console_admin_deactivate_user(user_id: int, request: Request, payload: dict[str, Any] | None = None):
    command = "admin_deactivate_user"
    owner = _require_owner_command_user(request, command)
    try:
        user = dependencies.get_user_service().deactivate_user(user_id=user_id)
    except ApplicationError as exc:
        _audit_command_failure(request, command, exc)
        raise HTTPException(status_code=exc.http_status, detail={"code": exc.code, "message": exc.message}) from exc
    _audit_command_success(
        request,
        command,
        {"target_user_id": user.id, "target_username": user.username, "owner_user_id": owner.id},
    )
    return {"success": True, "command": command, "summary": "User deactivated.", "user": _auth_user_payload(user)}


@router.post("/console/admin/users/{user_id}/mfa-reset")
def console_admin_reset_mfa(user_id: int, request: Request, payload: dict[str, Any] | None = None):
    command = "admin_reset_mfa"
    owner = _require_owner_command_user(request, command)
    try:
        user = dependencies.get_user_service().disable_mfa(user_id=user_id)
    except ApplicationError as exc:
        _audit_command_failure(request, command, exc)
        raise HTTPException(status_code=exc.http_status, detail={"code": exc.code, "message": exc.message}) from exc
    _audit_command_success(
        request,
        command,
        {"target_user_id": user.id, "target_username": user.username, "owner_user_id": owner.id},
    )
    return {"success": True, "command": command, "summary": "MFA reset for user.", "user": _auth_user_payload(user)}


def _auth_user_payload(user: AuthUser) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "display_name": user.display_name,
        "roles": list(user.roles),
        "is_active": user.is_active,
        "mfa_enabled": user.mfa_enabled,
    }


def _require_job(job_id: str):
    job = dependencies.get_job_service().get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
