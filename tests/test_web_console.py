from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from pete_e import api
from pete_e.api_routes import dependencies, web
from pete_e.application.api_services import StatusService
from pete_e.domain.auth import AuthUser, ROLE_OPERATOR, ROLE_OWNER, ROLE_READ_ONLY


class _Request:
    def __init__(
        self,
        *,
        path: str = "/console/status",
        cookies: dict[str, str] | None = None,
        query_params: dict[str, str] | None = None,
    ) -> None:
        self.method = "GET"
        self.headers = {}
        self.cookies = cookies or {}
        self.query_params = query_params or {}
        self.client = SimpleNamespace(host="127.0.0.1")
        self.scope = {"path": path}
        self.state = SimpleNamespace()


class _UserService:
    def __init__(self, user: AuthUser, *, token: str = "session-token") -> None:
        self.user = user
        self.token = token

    def validate_session_token(self, token: str):
        return self.user if token == self.token else None


class _StatusService:
    def run_checks(self, timeout: float):
        return [
            SimpleNamespace(name="DB", ok=True, detail="12ms"),
            SimpleNamespace(name="Withings", ok=False, detail="token expired"),
        ]

    def last_sync_outcome(self):
        return {
            "status": "observed",
            "label": "daily",
            "days": 1,
            "attempts": 2,
            "success": False,
            "source_statuses": {"AppleDropbox": "ok", "Withings": "failed"},
            "failed_sources": ["Withings"],
        }


class _MetricsService:
    def coach_state(self, iso_date: str):
        return {
            "summary": {
                "readiness_state": "amber",
                "data_reliability_flag": "moderate",
                "possible_underfueling_flag": False,
            },
            "derived": {
                "weight_rate_pct_bw_per_week": -0.4,
                "sleep_debt_7d_minutes": 180,
                "hrv_delta_vs_28d_ms": -3,
                "strength_load_7d_kg": 7200,
                "run_load_7d_km": 18.5,
            },
            "baselines": {
                "weight_avg_7d_kg": 89.2,
                "sleep_avg_7d_minutes": 405,
                "hrv_avg_7d_ms": 44,
            },
            "data_quality": {
                "last_sync_at": iso_date,
                "stale_days": 0,
                "completeness_pct": 86.7,
                "reliability_flag": "moderate",
            },
        }

    def daily_summary(self, iso_date: str):
        return {
            "date": iso_date,
            "metrics": {
                "weight_kg": {"value": 89.0},
                "sleep_asleep_minutes": {"value": 410},
                "hrv_sdnn_ms": {"value": 45},
                "strength_volume_kg": {"value": 5000},
            },
            "data_quality": {"status": "complete"},
        }

    def plan_context(self, iso_date: str):
        return {
            "date": iso_date,
            "active_plan": {"id": 42, "start_date": date(2026, 5, 11), "weeks": 4},
            "current_week_number": 1,
            "total_weeks": 4,
            "strength_phase": "build",
            "deload_due": False,
            "data_quality": "observed",
        }


class _PlanService:
    def for_week(self, iso_start_date: str):
        assert iso_start_date <= date.today().isoformat()
        return {
            "columns": ["workout_date", "exercise_name", "sets", "reps", "target_weight_kg"],
            "rows": [
                {
                    "workout_date": iso_start_date,
                    "exercise_name": "Bench Press",
                    "sets": 5,
                    "reps": 5,
                    "target_weight_kg": 82.5,
                }
            ],
        }

    def decision_trace(self, *, plan_id: int, week_number: int):
        assert plan_id == 42
        assert week_number == 1
        return {
            "plan_id": plan_id,
            "week_number": week_number,
            "trace": [
                {
                    "stage": "constraint_heavy_strength_run_quality",
                    "reason_code": "constraint_applied",
                }
            ],
        }


class _NutritionService:
    def __init__(self, *, meals_logged: int = 3) -> None:
        self.meals_logged = meals_logged

    def daily_summary(self, iso_date: str):
        return {
            "date": iso_date,
            "total_protein_g": 120,
            "total_carbs_g": 180,
            "total_fat_g": 70,
            "total_alcohol_g": 10,
            "total_fiber_g": 22,
            "total_estimated_calories": 1870,
            "meals_logged": self.meals_logged,
            "source_breakdown": {"photo_estimate": self.meals_logged} if self.meals_logged else {},
            "confidence_breakdown": {"medium": self.meals_logged} if self.meals_logged else {},
            "data_quality": {
                "status": "observed" if self.meals_logged else "missing",
                "nutrition_data_quality": "partial" if self.meals_logged else "missing",
                "last_logged_at": "2026-05-15T19:30:00",
            },
        }


def _body(response) -> str:
    body = getattr(response, "body", b"")
    if isinstance(body, bytes):
        return body.decode("utf-8")
    return str(body)


def _location(response) -> str | None:
    headers = getattr(response, "headers", {}) or {}
    return headers.get("location") or headers.get("Location")


def _user(*roles: str) -> AuthUser:
    return AuthUser(
        id=1,
        username="pete",
        email="pete@example.com",
        display_name="Pete",
        roles=roles or (ROLE_READ_ONLY,),
        is_active=True,
    )


def _install_console_services(monkeypatch: pytest.MonkeyPatch, user_service: _UserService) -> None:
    monkeypatch.setattr(dependencies, "get_user_service", lambda: user_service)
    monkeypatch.setattr(dependencies, "get_status_service", lambda: _StatusService())
    monkeypatch.setattr(dependencies, "get_metrics_service", lambda: _MetricsService())
    monkeypatch.setattr(dependencies, "get_plan_service", lambda: _PlanService())
    monkeypatch.setattr(dependencies, "get_nutrition_service", lambda: _NutritionService())


def test_console_route_redirects_unauthenticated_browser_request() -> None:
    response = web.console_status(_Request(path="/console/status"))

    assert response.status_code == 303
    assert _location(response) == "/login?next=/console/status"


def test_console_page_renders_authenticated_layout_with_read_only_nav(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_READ_ONLY))
    _install_console_services(monkeypatch, service)

    response = web.console_status(
        _Request(path="/console/status", cookies={dependencies.session_cookie_name(): service.token})
    )

    html = _body(response)
    assert response.status_code == 200
    assert "System Status" in html
    assert "Pete-Eebot" in html
    assert 'href="/console/plan"' in html
    assert 'href="/console/operations"' not in html
    assert 'href="/console/admin"' not in html


def test_status_page_renders_health_checks_and_source_level_sync_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _UserService(_user(ROLE_READ_ONLY))
    _install_console_services(monkeypatch, service)

    response = web.console_status(
        _Request(path="/console/status", cookies={dependencies.session_cookie_name(): service.token})
    )

    html = _body(response)
    assert response.status_code == 200
    assert "Health Checks" in html
    assert "token expired" in html
    assert "Last Sync Outcome" in html
    assert "AppleDropbox" in html
    assert "Withings" in html
    assert "failed" in html


def test_plan_page_renders_current_week_plan_and_decision_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_READ_ONLY))
    _install_console_services(monkeypatch, service)

    response = web.console_plan(_Request(path="/console/plan", cookies={dependencies.session_cookie_name(): service.token}))

    html = _body(response)
    assert response.status_code == 200
    assert "Current Week Plan" in html
    assert "Bench Press" in html
    assert "constraint_heavy_strength_run_quality" in html


def test_trends_page_renders_weight_sleep_hrv_and_volume_snapshots(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_READ_ONLY))
    _install_console_services(monkeypatch, service)

    response = web.console_trends(
        _Request(path="/console/trends", cookies={dependencies.session_cookie_name(): service.token})
    )

    html = _body(response)
    assert response.status_code == 200
    assert "Weight" in html
    assert "Sleep" in html
    assert "HRV" in html
    assert "Volume" in html
    assert "89.2" in html
    assert "7200" in html


def test_nutrition_page_renders_daily_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_READ_ONLY))
    _install_console_services(monkeypatch, service)

    response = web.console_nutrition(
        _Request(path="/console/nutrition", cookies={dependencies.session_cookie_name(): service.token})
    )

    html = _body(response)
    assert response.status_code == 200
    assert "Macro Totals" in html
    assert "120" in html
    assert "1870 kcal" in html
    assert "photo_estimate" in html


def test_nutrition_page_renders_missing_daily_summary_state(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_READ_ONLY))
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    monkeypatch.setattr(dependencies, "get_status_service", lambda: _StatusService())
    monkeypatch.setattr(dependencies, "get_metrics_service", lambda: _MetricsService())
    monkeypatch.setattr(dependencies, "get_plan_service", lambda: _PlanService())
    monkeypatch.setattr(dependencies, "get_nutrition_service", lambda: _NutritionService(meals_logged=0))

    response = web.console_nutrition(
        _Request(path="/console/nutrition", cookies={dependencies.session_cookie_name(): service.token})
    )

    html = _body(response)
    assert response.status_code == 200
    assert "No nutrition entries logged for today." in html


def test_status_service_reads_latest_sync_outcome_from_log(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_path = tmp_path / "pete_history.log"
    log_path.write_text(
        "\n".join(
            [
                "[2026-05-15T07:00:00Z] [INFO] [SYNC] Sync summary: run=daily | days=1 | "
                "attempts=1 | result=success | Withings=ok",
                "[2026-05-15T08:00:00Z] [ERROR] [SYNC] Sync summary: run=daily | days=1 | "
                "attempts=2 | result=failed | AppleDropbox=ok, Withings=failed, Wger=ok",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("pete_e.application.api_services.settings", SimpleNamespace(log_path=log_path))

    payload = StatusService(dal=None).last_sync_outcome()

    assert payload["status"] == "observed"
    assert payload["success"] is False
    assert payload["failed_sources"] == ["Withings"]
    assert payload["source_statuses"]["AppleDropbox"] == "ok"


def test_operator_nav_shows_operator_page_but_hides_owner_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)

    response = web.console_plan(_Request(path="/console/plan", cookies={dependencies.session_cookie_name(): service.token}))

    html = _body(response)
    assert 'href="/console/operations"' in html
    assert 'href="/console/admin"' not in html


def test_owner_nav_shows_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_OWNER))
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)

    response = web.console_admin(_Request(path="/console/admin", cookies={dependencies.session_cookie_name(): service.token}))

    html = _body(response)
    assert response.status_code == 200
    assert "Owner access confirmed." in html
    assert 'href="/console/admin"' in html


def test_read_only_user_cannot_open_operator_page(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_READ_ONLY))
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)

    with pytest.raises(web.HTTPException) as exc:
        web.console_operations(
            _Request(path="/console/operations", cookies={dependencies.session_cookie_name(): service.token})
        )

    assert exc.value.status_code == 403


def test_web_routes_are_mounted_once_outside_api_v1_namespace() -> None:
    mounted_routes = {
        (method, route.path)
        for route in getattr(api.app, "routes", [])
        for method in getattr(route, "methods", set())
    }

    assert ("GET", "/console/status") in mounted_routes
    assert ("GET", "/login") in mounted_routes
    assert ("GET", f"{api.API_V1_PREFIX}/console/status") not in mounted_routes
