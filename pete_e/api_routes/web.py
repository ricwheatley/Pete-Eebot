from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import fastapi
from fastapi import HTTPException, Request
from jinja2 import Environment, FileSystemLoader, select_autoescape

from pete_e.api_routes import dependencies
from pete_e.api_routes.dependencies import current_user_from_session, require_browser_user
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


def _operator_today() -> date:
    try:
        timezone = ZoneInfo(str(getattr(settings, "USER_TIMEZONE", "Europe/London")))
    except ZoneInfoNotFoundError:
        return date.today()
    return datetime.now(timezone).date()


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
    return _render_console(request, "operations", min_role=ROLE_OPERATOR)


@router.get("/console/admin")
def console_admin(request: Request):
    return _render_console(request, "admin", min_role=ROLE_OWNER)
