from __future__ import annotations

import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from pete_e import api
from pete_e.api_routes import dependencies, web
from pete_e.application.sync import SyncResult
from pete_e.application.api_services import StatusService
from pete_e.domain.auth import AuthUser, ROLE_OPERATOR, ROLE_OWNER, ROLE_READ_ONLY
from pete_e.domain.daily_sync import AppleHealthImportSummary, AppleHealthIngestResult
from pete_e.domain.jobs import ApplicationJob, CommandHistoryEntry


class _Request:
    def __init__(
        self,
        *,
        path: str = "/console/status",
        method: str = "GET",
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        query_params: dict[str, str] | None = None,
    ) -> None:
        self.method = method
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.query_params = query_params or {}
        self.client = SimpleNamespace(host="127.0.0.1")
        self.scope = {"path": path}
        self.state = SimpleNamespace()


class _UserService:
    def __init__(self, user: AuthUser, *, token: str = "session-token") -> None:
        self.user = user
        self.token = token
        self.users = [user]
        self.created = []
        self.role_updates = []
        self.deactivated = []
        self.mfa_disabled = []

    def validate_session_token(self, token: str):
        return self.user if token == self.token else None

    def list_users(self):
        return self.users

    def create_user(self, **kwargs):
        user = AuthUser(
            id=2,
            username=kwargs["username"],
            email=kwargs.get("email"),
            display_name=kwargs.get("display_name"),
            roles=tuple(kwargs.get("roles") or (ROLE_READ_ONLY,)),
            is_active=True,
        )
        self.created.append(kwargs)
        self.users.append(user)
        return user

    def set_user_roles(self, *, user_id: int, roles):
        self.role_updates.append({"user_id": user_id, "roles": tuple(roles)})
        user = self.users[0]
        updated = AuthUser(
            id=user_id,
            username=user.username,
            email=user.email,
            display_name=user.display_name,
            roles=tuple(roles),
            is_active=user.is_active,
            mfa_enabled=user.mfa_enabled,
        )
        self.users[0] = updated
        return updated

    def deactivate_user(self, *, user_id: int):
        self.deactivated.append(user_id)
        user = self.users[0]
        updated = AuthUser(
            id=user.id,
            username=user.username,
            email=user.email,
            display_name=user.display_name,
            roles=user.roles,
            is_active=False,
            mfa_enabled=user.mfa_enabled,
        )
        self.users[0] = updated
        return updated

    def disable_mfa(self, *, user_id: int):
        self.mfa_disabled.append(user_id)
        user = self.users[0]
        return AuthUser(
            id=user.id,
            username=user.username,
            email=user.email,
            display_name=user.display_name,
            roles=user.roles,
            is_active=user.is_active,
            mfa_enabled=False,
        )

    def start_mfa_enrollment(self, user):
        return {"secret": "JBSWY3DPEHPK3PXP", "otp_uri": "otpauth://totp/Pete-Eebot:pete", "recovery_codes": ["ABCD-EFGH-IJKL-MNOP"], "user": user}

    def confirm_mfa_enrollment(self, user, code):
        if code != "123456":
            raise web.BadRequestError("Invalid MFA code", code="invalid_mfa_code")
        return AuthUser(
            id=user.id,
            username=user.username,
            email=user.email,
            display_name=user.display_name,
            roles=user.roles,
            is_active=user.is_active,
            mfa_enabled=True,
        )


class _StatusService:
    def run_checks(self, timeout: float):
        return [
            SimpleNamespace(name="DB", ok=True, detail="12ms"),
            SimpleNamespace(name="Withings", ok=False, detail="token expired"),
        ]

    def last_sync_outcome(self):
        return {
            "status": "observed",
            "ran_at": "2026-05-15T08:00:00.000Z",
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
        self.created = []
        self.updated = []

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

    def daily_logs(self, iso_date: str, *, limit: int = 25):
        if not self.meals_logged:
            return []
        return [
            {
                "id": 5,
                "eaten_at": f"{iso_date}T12:00:00+00:00",
                "local_date": iso_date,
                "protein_g": 40,
                "carbs_g": 55,
                "fat_g": 20,
                "alcohol_g": 0,
                "fiber_g": 5,
                "estimated_total_calories": None,
                "calories_est": 560,
                "source": "photo_estimate",
                "context": None,
                "confidence": "medium",
                "meal_label": "Lunch",
                "notes": None,
                "client_event_id": None,
            }
        ]

    def log_macros(self, payload):
        self.created.append(payload)
        return {"id": 9, "local_date": date.today().isoformat(), "protein_g": payload.get("protein_g")}

    def update_log(self, log_id, payload):
        self.updated.append({"log_id": log_id, "payload": payload})
        return {"id": log_id, "local_date": date.today().isoformat(), **payload}


class _JobService:
    def __init__(self) -> None:
        self.enqueued: list[dict] = []
        self.command_events: list[dict] = []
        self.history = [
            CommandHistoryEntry(
                id=7,
                request_id="req-123",
                correlation_id="req-123",
                job_id="plan-job-1",
                requester_user_id=1,
                requester_username="pete",
                auth_scheme="session",
                command="plan",
                outcome="succeeded",
                safe_summary={"weeks": 4, "start_date": "2026-05-18"},
                client_identity="127.0.0.1",
                created_at=datetime(2026, 5, 15, 9, 2, tzinfo=timezone.utc),
            )
        ]
        self.jobs = [
            ApplicationJob(
                id="plan-job-1",
                operation="plan",
                requester_user_id=1,
                requester_username="pete",
                status="succeeded",
                request_id="req-123",
                correlation_id="req-123",
                request_summary={"weeks": 4, "start_date": "2026-05-18"},
                created_at=datetime(2026, 5, 15, 9, 0, tzinfo=timezone.utc),
                started_at=datetime(2026, 5, 15, 9, 1, tzinfo=timezone.utc),
                completed_at=datetime(2026, 5, 15, 9, 2, tzinfo=timezone.utc),
                exit_code=0,
                result_summary="plan completed successfully.",
                stdout_summary="created plan 42",
            )
        ]

    def enqueue_subprocess(self, **kwargs):
        self.enqueued.append(kwargs)
        return ApplicationJob(
            id=kwargs["job_id"],
            operation=kwargs["operation"],
            requester_user_id=kwargs["requester"].id,
            requester_username=kwargs["requester"].username,
            status="queued",
            request_id=kwargs["request_id"],
            correlation_id=kwargs["correlation_id"],
            request_summary=kwargs["request_summary"],
        )

    def run_callback(self, **kwargs):
        self.enqueued.append(kwargs)
        return kwargs["callback"]()

    def list_recent_jobs(self, *, limit: int = 25):
        return self.jobs[:limit]

    def list_current_jobs(self, *, limit: int = 10):
        return [job for job in self.jobs if not job.is_terminal][:limit]

    def get_job(self, job_id: str):
        return next((job for job in self.jobs if job.id == job_id), None)

    def record_command_event(self, **kwargs):
        self.command_events.append(kwargs)
        entry = CommandHistoryEntry(
            id=len(self.command_events),
            request_id=kwargs["request_id"],
            correlation_id=kwargs["correlation_id"],
            job_id=kwargs["job_id"],
            requester_user_id=kwargs["requester"].id if kwargs["requester"] is not None else None,
            requester_username=kwargs["requester"].username if kwargs["requester"] is not None else None,
            auth_scheme=kwargs["auth_scheme"],
            command=kwargs["command"],
            outcome=kwargs["outcome"],
            safe_summary=kwargs["summary"],
            client_identity=kwargs["client_identity"],
        )
        self.history.insert(0, entry)
        return entry

    def list_command_history(
        self,
        *,
        limit: int = 25,
        query: str | None = None,
        command: str | None = None,
        outcome: str | None = None,
    ):
        rows = self.history
        if command:
            rows = [entry for entry in rows if entry.command == command]
        if outcome:
            rows = [entry for entry in rows if entry.outcome == outcome]
        if query:
            needle = query.lower()
            rows = [
                entry
                for entry in rows
                if needle in entry.request_id.lower()
                or (entry.job_id and needle in entry.job_id.lower())
                or (entry.requester_username and needle in entry.requester_username.lower())
            ]
        return rows[:limit]


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
    monkeypatch.setattr(dependencies, "get_job_service", lambda: _JobService())


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
    assert 'href="/console/logs"' in html
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
    assert "Attempted" in html
    assert "15/05/2026 08:00:00" in html
    assert "2026-05-15T08:00:00.000Z" not in html
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
    assert "6.8" in html
    assert " h" in html


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
    assert "15/05/2026 19:30:00" in html
    assert "2026-05-15T19:30:00" not in html
    assert "Save nutrition log" not in html


def test_nutrition_page_shows_mutation_controls_for_operator(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    _install_console_services(monkeypatch, service)

    response = web.console_nutrition(
        _Request(path="/console/nutrition", cookies={dependencies.session_cookie_name(): service.token})
    )

    html = _body(response)
    assert response.status_code == 200
    assert "Add Nutrition Log" in html
    assert "Save nutrition log" in html
    assert 'data-endpoint="/console/nutrition/logs/5"' in html


def test_console_nutrition_create_and_edit_use_service_validation_and_csrf(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    nutrition_service = _NutritionService()
    csrf_token = dependencies.generate_csrf_token(service.token)
    audit_events: list[dict] = []
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    monkeypatch.setattr(dependencies, "get_nutrition_service", lambda: nutrition_service)
    monkeypatch.setattr(dependencies, "enforce_command_rate_limit", lambda request, command: None)
    monkeypatch.setattr(dependencies, "audit_command_event", lambda request, **event: audit_events.append(event))

    request = _Request(
        path="/console/nutrition/logs",
        method="POST",
        headers={dependencies.CSRF_HEADER_NAME: csrf_token},
        cookies={
            dependencies.session_cookie_name(): service.token,
            dependencies.csrf_cookie_name(): csrf_token,
        },
    )
    created = web.console_create_nutrition_log(request, payload={"protein_g": "40", "carbs_g": "55", "fat_g": "20", "notes": ""})
    updated = web.console_update_nutrition_log(5, request, payload={"protein_g": "45", "meal_label": "Dinner"})

    assert created["success"] is True
    assert updated["success"] is True
    assert nutrition_service.created[0] == {"protein_g": "40", "carbs_g": "55", "fat_g": "20"}
    assert nutrition_service.updated[0] == {"log_id": 5, "payload": {"protein_g": "45", "meal_label": "Dinner"}}
    assert [event["outcome"] for event in audit_events] == ["succeeded", "succeeded"]


def test_console_nutrition_mutation_requires_operator_role(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_READ_ONLY))
    csrf_token = dependencies.generate_csrf_token(service.token)
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    monkeypatch.setattr(dependencies, "audit_command_event", lambda request, **event: None)

    with pytest.raises(web.HTTPException) as exc:
        web.console_create_nutrition_log(
            _Request(
                path="/console/nutrition/logs",
                method="POST",
                headers={dependencies.CSRF_HEADER_NAME: csrf_token},
                cookies={
                    dependencies.session_cookie_name(): service.token,
                    dependencies.csrf_cookie_name(): csrf_token,
                },
            ),
            payload={"protein_g": "40", "carbs_g": "55", "fat_g": "20"},
        )

    assert exc.value.status_code == 403


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


def test_logs_page_renders_recent_log_fields_for_read_only_user(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "pete_history.log"
    log_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-05-15T08:00:00.000Z",
                        "level": "INFO",
                        "tag": "API",
                        "message": "GET /api/v1/status 200",
                        "request_id": "req-123",
                        "outcome": "succeeded",
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-05-15T08:01:00.000Z",
                        "level": "ERROR",
                        "tag": "AUDIT",
                        "message": "CHECKPOINT operator_command failed",
                        "outcome": "failed",
                        "correlation": {"request_id": "req-456", "job_id": "sync-abc"},
                    }
                ),
                "[2026-05-15T08:02:00Z] [WARNING] [SYNC] Sync summary: run=daily",
            ]
        ),
        encoding="utf-8",
    )
    service = _UserService(_user(ROLE_READ_ONLY))
    _install_console_services(monkeypatch, service)
    monkeypatch.setattr(type(api.settings), "log_path", property(lambda self: log_path))

    response = web.console_logs(
        _Request(path="/console/logs", cookies={dependencies.session_cookie_name(): service.token})
    )

    html = _body(response)
    assert response.status_code == 200
    assert "Recent Lines" in html
    assert "15/05/2026 08:00:00" in html
    assert "2026-05-15T08:00:00.000Z" not in html
    assert "req-123" in html
    assert "sync-abc" in html
    assert "AUDIT" in html
    assert "failed" in html
    assert "Sync summary: run=daily" in html


def test_logs_page_filters_by_tag_and_outcome(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_path = tmp_path / "pete_history.log"
    log_path.write_text(
        "\n".join(
            [
                json.dumps({"level": "INFO", "tag": "API", "outcome": "succeeded", "message": "status ok"}),
                json.dumps(
                    {
                        "level": "ERROR",
                        "tag": "JOB",
                        "outcome": "failed",
                        "message": "job sync failed",
                        "job_id": "sync-failed",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    service = _UserService(_user(ROLE_READ_ONLY))
    _install_console_services(monkeypatch, service)
    monkeypatch.setattr(type(api.settings), "log_path", property(lambda self: log_path))

    response = web.console_logs(
        _Request(
            path="/console/logs",
            cookies={dependencies.session_cookie_name(): service.token},
            query_params={"lines": "100", "tag": "JOB", "outcome": "failed"},
        )
    )

    html = _body(response)
    assert response.status_code == 200
    assert "job sync failed" in html
    assert "sync-failed" in html
    assert "status ok" not in html


def test_alerts_page_renders_filtered_alert_history(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_path = tmp_path / "pete_history.log"
    log_path.write_text(
        json.dumps(
            {
                "event": "alert_event",
                "timestamp": "2026-05-15T08:00:00+00:00",
                "level": "ERROR",
                "tag": "ALERT",
                "message": "alert auth_expiry P1",
                "alert_type": "auth_expiry",
                "severity": "P1",
                "outcome": "emitted",
                "dedupe_key": "auth_expiry:withings",
                "summary": {"message": "Withings authorization needs attention", "job_id": "sync-1"},
            }
        ),
        encoding="utf-8",
    )
    service = _UserService(_user(ROLE_OPERATOR))
    _install_console_services(monkeypatch, service)
    monkeypatch.setattr(type(api.settings), "log_path", property(lambda self: log_path))

    response = web.console_alerts(
        _Request(
            path="/console/alerts",
            cookies={dependencies.session_cookie_name(): service.token},
            query_params={"severity": "P1", "type": "auth_expiry"},
        )
    )

    html = _body(response)
    assert response.status_code == 200
    assert "Active Alerts" in html
    assert "auth_expiry" in html
    assert "15/05/2026 08:00:00" in html
    assert "2026-05-15T08:00:00+00:00" not in html
    assert "Withings authorization needs attention" in html
    assert "sync-1" in html


def test_scheduler_page_renders_expected_cron_and_break_glass_links(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    _install_console_services(monkeypatch, service)

    response = web.console_scheduler(
        _Request(path="/console/scheduler", cookies={dependencies.session_cookie_name(): service.token})
    )

    html = _body(response)
    assert response.status_code == 200
    assert "Expected Cron Entries" in html
    assert "daily sync" in html
    assert "heartbeat check" in html
    assert "Cron repair" in html


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


def test_status_service_parses_json_sync_summary_without_json_tail(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "pete_history.log"
    log_path.write_text(
        json.dumps(
            {
                "timestamp": "2026-05-15T08:00:00.000Z",
                "level": "ERROR",
                "tag": "SYNC",
                "message": (
                    "Sync summary: run=daily | days=7 | attempts=3 | result=failed | "
                    "Apple Health=failed, Database=failed, Withings=ok\n"
                    "Withings data unavailable across last 7 days"
                ),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("pete_e.application.api_services.settings", SimpleNamespace(log_path=log_path))

    payload = StatusService(dal=None).last_sync_outcome()

    assert payload["ran_at"] == "2026-05-15T08:00:00.000Z"
    assert payload["source_statuses"] == {
        "Apple Health": "failed",
        "Database": "failed",
        "Withings": "ok",
    }


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
    assert "Create User" in html
    assert 'href="/console/admin"' in html


def test_admin_mutations_require_owner_and_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_OWNER))
    csrf_token = dependencies.generate_csrf_token(service.token)
    audit_events: list[dict] = []
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    monkeypatch.setattr(dependencies, "audit_command_event", lambda request, **event: audit_events.append(event))
    request = _Request(
        path="/console/admin/users",
        method="POST",
        headers={dependencies.CSRF_HEADER_NAME: csrf_token},
        cookies={
            dependencies.session_cookie_name(): service.token,
            dependencies.csrf_cookie_name(): csrf_token,
        },
    )

    created = web.console_admin_create_user(
        request,
        payload={
            "username": "operator",
            "password": "password123",
            "roles": [ROLE_OPERATOR, ROLE_READ_ONLY],
        },
    )
    roles = web.console_admin_update_roles(1, request, payload={"roles": [ROLE_OPERATOR]})
    deactivated = web.console_admin_deactivate_user(1, request, payload={})

    assert created["user"]["username"] == "operator"
    assert roles["user"]["roles"] == [ROLE_OPERATOR]
    assert deactivated["user"]["is_active"] is False
    assert service.created[0]["roles"] == (ROLE_OPERATOR, ROLE_READ_ONLY)
    assert service.role_updates[0] == {"user_id": 1, "roles": (ROLE_OPERATOR,)}
    assert service.deactivated == [1]
    assert [event["command"] for event in audit_events] == [
        "admin_create_user",
        "admin_update_roles",
        "admin_deactivate_user",
    ]
    assert all(event["outcome"] == "succeeded" for event in audit_events)


def test_admin_page_requires_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)

    with pytest.raises(web.HTTPException) as exc:
        web.console_admin(_Request(path="/console/admin", cookies={dependencies.session_cookie_name(): service.token}))

    assert exc.value.status_code == 403


def test_read_only_user_cannot_open_operator_page(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_READ_ONLY))
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)

    with pytest.raises(web.HTTPException) as exc:
        web.console_operations(
            _Request(path="/console/operations", cookies={dependencies.session_cookie_name(): service.token})
        )

    assert exc.value.status_code == 403


def test_operations_page_renders_confirmed_command_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)

    response = web.console_operations(
        _Request(path="/console/operations", cookies={dependencies.session_cookie_name(): service.token})
    )

    html = _body(response)
    assert response.status_code == 200
    assert "Run Sync" in html
    assert "Withings Sync" in html
    assert "Apple Ingest" in html
    assert "Generate Plan" in html
    assert "Run Sunday Review" in html
    assert "Start Strength Test Week" in html
    assert "Preview Message" in html
    assert "Resend Message" in html
    assert "Preview Morning Report" in html
    assert "Send Morning Report" in html
    assert "RUN SYNC" in html
    assert "RUN WITHINGS SYNC" in html
    assert "RUN APPLE INGEST" in html
    assert "GENERATE PLAN" in html
    assert "RUN SUNDAY REVIEW" in html
    assert "BEGIN STRENGTH TEST" in html
    assert "Confirm start date" in html
    assert "RESEND MESSAGE" in html
    assert "SEND MORNING REPORT" in html
    assert "Break-Glass References" in html
    assert "OAuth recovery" in html
    assert "Backup and restore" in html
    assert "Cron repair" in html
    assert 'data-endpoint="/console/operations/run-sync"' in html
    assert 'data-endpoint="/console/operations/run-withings-sync"' in html
    assert 'data-endpoint="/console/operations/ingest-apple"' in html
    assert 'data-endpoint="/console/operations/run-sunday-review"' in html
    assert 'data-endpoint="/console/operations/lets-begin"' in html
    assert 'data-endpoint="/console/operations/preview-message"' in html
    assert 'data-endpoint="/console/operations/morning-report-preview"' in html
    assert 'data-endpoint="/console/operations/morning-report-send"' in html


def test_jobs_page_renders_recent_jobs_for_operator(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    job_service = _JobService()
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    monkeypatch.setattr(dependencies, "get_job_service", lambda: job_service)

    response = web.console_jobs(
        _Request(path="/console/jobs", cookies={dependencies.session_cookie_name(): service.token})
    )

    html = _body(response)
    assert response.status_code == 200
    assert "Current Jobs" in html
    assert "Recent Jobs" in html
    assert "plan-job-1" in html
    assert "succeeded" in html
    assert "15/05/2026 09:00:00" in html
    assert "2026-05-15 09:00:00+00:00" not in html


def test_command_history_page_renders_searchable_audit_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    job_service = _JobService()
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    monkeypatch.setattr(dependencies, "get_job_service", lambda: job_service)

    response = web.console_command_history(
        _Request(
            path="/console/history",
            cookies={dependencies.session_cookie_name(): service.token},
            query_params={"q": "plan-job", "command": "plan", "outcome": "succeeded"},
        )
    )

    html = _body(response)
    assert response.status_code == 200
    assert "Command History" in html
    assert "plan-job-1" in html
    assert "req-123" in html
    assert "session" in html
    assert "start_date" in html
    assert "15/05/2026 09:02:00" in html
    assert "2026-05-15 09:02:00+00:00" not in html


def test_command_history_api_returns_recent_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    job_service = _JobService()
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    monkeypatch.setattr(dependencies, "get_job_service", lambda: job_service)

    response = web.console_command_history_api(
        _Request(path="/console/history.json", cookies={dependencies.session_cookie_name(): service.token}),
    )

    body = getattr(response, "content", None)
    if body is None:
        body = json.loads(getattr(response, "body", b"{}").decode("utf-8"))
    assert response.status_code == 200
    assert body["entries"][0]["request_id"] == "req-123"
    assert body["entries"][0]["job_id"] == "plan-job-1"
    assert body["entries"][0]["auth_scheme"] == "session"


def test_job_status_api_requires_operator_and_returns_job_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    job_service = _JobService()
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    monkeypatch.setattr(dependencies, "get_job_service", lambda: job_service)

    response = web.console_job_status(
        _Request(path="/console/jobs/plan-job-1/status", cookies={dependencies.session_cookie_name(): service.token}),
        "plan-job-1",
    )

    body = getattr(response, "content", None)
    if body is None:
        body = json.loads(getattr(response, "body", b"{}").decode("utf-8"))
    assert response.status_code == 200
    assert body == {
        "job": job_service.jobs[0].to_status_payload(),
    }


def test_console_command_requires_operator_role_before_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_READ_ONLY))
    csrf_token = dependencies.generate_csrf_token(service.token)
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)

    with pytest.raises(web.HTTPException) as exc:
        web.console_run_sync(
            _Request(
                path="/console/operations/run-sync",
                method="POST",
                headers={dependencies.CSRF_HEADER_NAME: csrf_token},
                cookies={
                    dependencies.session_cookie_name(): service.token,
                    dependencies.csrf_cookie_name(): csrf_token,
                },
            ),
            payload={"confirmation": "RUN SYNC"},
        )

    assert exc.value.status_code == 403


def test_console_command_requires_csrf_before_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)

    with pytest.raises(web.HTTPException) as exc:
        web.console_run_sync(
            _Request(
                path="/console/operations/run-sync",
                method="POST",
                cookies={dependencies.session_cookie_name(): service.token},
            ),
            payload={"confirmation": "RUN SYNC"},
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "csrf_required"


def test_console_command_requires_exact_confirmation_and_audits_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    csrf_token = dependencies.generate_csrf_token(service.token)
    audit_events: list[dict] = []
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    monkeypatch.setattr(
        dependencies,
        "audit_command_event",
        lambda request, **event: audit_events.append(event),
    )

    with pytest.raises(web.HTTPException) as exc:
        web.console_run_sync(
            _Request(
                path="/console/operations/run-sync",
                method="POST",
                headers={dependencies.CSRF_HEADER_NAME: csrf_token},
                cookies={
                    dependencies.session_cookie_name(): service.token,
                    dependencies.csrf_cookie_name(): csrf_token,
                },
            ),
            payload={"confirmation": "sync please"},
        )

    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "confirmation_required"
    assert audit_events[-1]["command"] == "sync"
    assert audit_events[-1]["outcome"] == "confirmation_failed"


def test_console_run_sync_executes_after_confirmation_and_audits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    csrf_token = dependencies.generate_csrf_token(service.token)
    audit_events: list[dict] = []
    captured: dict[str, tuple[int, int]] = {}
    job_service = _JobService()
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    monkeypatch.setattr(dependencies, "enforce_command_rate_limit", lambda request, command: None)
    monkeypatch.setattr(dependencies, "prepare_job_context", lambda request, operation: "sync-job-test")
    monkeypatch.setattr(dependencies, "get_job_service", lambda: job_service)
    monkeypatch.setattr(
        dependencies,
        "audit_command_event",
        lambda request, **event: audit_events.append(event),
    )

    def _sync(days: int, retries: int) -> SyncResult:
        captured["args"] = (days, retries)
        return SyncResult(
            success=True,
            attempts=1,
            failed_sources=[],
            source_statuses={"Withings": "ok"},
            label="manual",
            undelivered_alerts=[],
        )

    monkeypatch.setattr(web, "run_sync_with_retries", _sync)

    payload = web.console_run_sync(
        _Request(
            path="/console/operations/run-sync",
            method="POST",
            headers={dependencies.CSRF_HEADER_NAME: csrf_token},
            cookies={
                dependencies.session_cookie_name(): service.token,
                dependencies.csrf_cookie_name(): csrf_token,
            },
        ),
        payload={"confirmation": "RUN SYNC", "days": 2, "retries": 0},
    )

    assert captured["args"] == (2, 0)
    assert payload["status"] == "completed"
    assert payload["job_id"] == "sync-job-test"
    assert payload["success"] is True
    assert job_service.enqueued[0]["operation"] == "sync"
    assert [event["outcome"] for event in audit_events] == ["started", "succeeded"]


def test_console_run_withings_sync_uses_job_service_and_reports_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    csrf_token = dependencies.generate_csrf_token(service.token)
    audit_events: list[dict] = []
    captured: dict[str, tuple[int, int]] = {}
    job_service = _JobService()
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    monkeypatch.setattr(dependencies, "enforce_command_rate_limit", lambda request, command: None)
    monkeypatch.setattr(dependencies, "prepare_job_context", lambda request, operation: "withings-job-test")
    monkeypatch.setattr(dependencies, "get_job_service", lambda: job_service)
    monkeypatch.setattr(
        dependencies,
        "audit_command_event",
        lambda request, **event: audit_events.append(event),
    )

    def _withings(days: int, retries: int) -> SyncResult:
        captured["args"] = (days, retries)
        return SyncResult(
            success=False,
            attempts=2,
            failed_sources=["Withings"],
            source_statuses={"Withings": "failed", "Database": "ok"},
            label="withings-only",
            undelivered_alerts=[],
        )

    monkeypatch.setattr(web, "run_withings_only_with_retries", _withings)

    payload = web.console_run_withings_sync(
        _Request(
            path="/console/operations/run-withings-sync",
            method="POST",
            headers={dependencies.CSRF_HEADER_NAME: csrf_token},
            cookies={
                dependencies.session_cookie_name(): service.token,
                dependencies.csrf_cookie_name(): csrf_token,
            },
        ),
        payload={"confirmation": "RUN WITHINGS SYNC", "days": 7, "retries": 2},
    )

    assert captured["args"] == (7, 2)
    assert payload["status"] == "completed"
    assert payload["job_id"] == "withings-job-test"
    assert payload["success"] is False
    assert payload["source_statuses"] == {"Withings": "failed", "Database": "ok"}
    assert "Withings=failed" in payload["summary"]
    assert job_service.enqueued[0]["operation"] == "withings_sync"
    assert job_service.enqueued[0]["request_summary"] == {"days": 7, "retries": 2, "source": "Withings"}
    assert [event["outcome"] for event in audit_events] == ["started", "succeeded"]
    assert audit_events[-1]["summary"]["source_statuses"]["Withings"] == "failed"


def test_console_apple_ingest_uses_job_service_and_reports_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    csrf_token = dependencies.generate_csrf_token(service.token)
    audit_events: list[dict] = []
    job_service = _JobService()
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    monkeypatch.setattr(dependencies, "enforce_command_rate_limit", lambda request, command: None)
    monkeypatch.setattr(dependencies, "prepare_job_context", lambda request, operation: "apple-job-test")
    monkeypatch.setattr(dependencies, "get_job_service", lambda: job_service)
    monkeypatch.setattr(
        dependencies,
        "audit_command_event",
        lambda request, **event: audit_events.append(event),
    )

    def _apple() -> AppleHealthIngestResult:
        return AppleHealthIngestResult(
            success=True,
            summary=AppleHealthImportSummary(
                sources=("HealthAutoExport-1.json",),
                workouts=3,
                daily_points=42,
                hr_days=2,
                sleep_days=1,
            ),
            failures=(),
            statuses={"Apple Health": "ok"},
            alerts=(),
        )

    monkeypatch.setattr(web, "run_apple_health_ingest", _apple)

    payload = web.console_ingest_apple(
        _Request(
            path="/console/operations/ingest-apple",
            method="POST",
            headers={dependencies.CSRF_HEADER_NAME: csrf_token},
            cookies={
                dependencies.session_cookie_name(): service.token,
                dependencies.csrf_cookie_name(): csrf_token,
            },
        ),
        payload={"confirmation": "RUN APPLE INGEST"},
    )

    assert payload["status"] == "completed"
    assert payload["job_id"] == "apple-job-test"
    assert payload["success"] is True
    assert payload["source_statuses"] == {"Apple Health": "ok"}
    assert payload["failed_sources"] == []
    assert payload["import_summary"]["source_file_count"] == 1
    assert "Apple Health=ok" in payload["summary"]
    assert "workouts=3" in payload["summary"]
    assert job_service.enqueued[0]["operation"] == "apple_ingest"
    assert job_service.enqueued[0]["request_summary"] == {"source": "Apple Health"}
    assert [event["outcome"] for event in audit_events] == ["started", "succeeded"]
    assert audit_events[-1]["summary"]["source_statuses"] == {"Apple Health": "ok"}


def test_console_plan_and_resend_commands_start_expected_processes(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    csrf_token = dependencies.generate_csrf_token(service.token)
    job_service = _JobService()
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    monkeypatch.setattr(dependencies, "enforce_command_rate_limit", lambda request, command: None)
    monkeypatch.setattr(dependencies, "audit_command_event", lambda request, **event: None)
    monkeypatch.setattr(dependencies, "prepare_job_context", lambda request, operation: "plan-job-test")
    monkeypatch.setattr(dependencies, "get_job_service", lambda: job_service)
    request = _Request(
        path="/console/operations/generate-plan",
        method="POST",
        headers={dependencies.CSRF_HEADER_NAME: csrf_token, "X-Request-ID": "req-plan-1"},
        cookies={
            dependencies.session_cookie_name(): service.token,
            dependencies.csrf_cookie_name(): csrf_token,
        },
    )

    plan_payload = web.console_generate_plan(
        request,
        payload={"confirmation": "GENERATE PLAN", "weeks": 4, "start_date": "2026-05-18"},
    )
    message_payload = web.console_resend_message(
        request,
        payload={"confirmation": "RESEND MESSAGE", "message_type": "trainer"},
    )

    assert plan_payload == {
        "status": "queued",
        "command": "plan",
        "job_id": "plan-job-test",
        "status_url": "/console/jobs/plan-job-test",
        "status_api_url": "/console/jobs/plan-job-test/status",
        "weeks": 4,
        "start_date": "2026-05-18",
    }
    assert message_payload == {
        "status": "queued",
        "command": "message_resend",
        "job_id": "plan-job-test",
        "status_url": "/console/jobs/plan-job-test",
        "status_api_url": "/console/jobs/plan-job-test/status",
        "message_type": "trainer",
    }
    assert job_service.enqueued[0]["command"] == ["pete", "plan", "--weeks", "4", "--start-date", "2026-05-18"]
    assert job_service.enqueued[0]["requester"].username == "pete"
    assert job_service.enqueued[0]["request_id"] == "req-plan-1"
    assert job_service.enqueued[1]["command"] == ["pete", "message", "--trainer", "--send"]
    assert job_service.enqueued[1]["operation"] == "message_resend"


def test_console_weekly_review_and_lets_begin_start_guarded_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    csrf_token = dependencies.generate_csrf_token(service.token)
    job_service = _JobService()
    audit_events: list[dict] = []
    job_ids = {"sunday_review": "review-job-test", "lets_begin": "lets-begin-job-test"}
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    monkeypatch.setattr(dependencies, "enforce_command_rate_limit", lambda request, command: None)
    monkeypatch.setattr(dependencies, "audit_command_event", lambda request, **event: audit_events.append(event))
    monkeypatch.setattr(dependencies, "prepare_job_context", lambda request, operation: job_ids[operation])
    monkeypatch.setattr(dependencies, "get_job_service", lambda: job_service)
    request = _Request(
        path="/console/operations/run-sunday-review",
        method="POST",
        headers={dependencies.CSRF_HEADER_NAME: csrf_token, "X-Request-ID": "req-review-1"},
        cookies={
            dependencies.session_cookie_name(): service.token,
            dependencies.csrf_cookie_name(): csrf_token,
        },
    )

    review_payload = web.console_run_sunday_review(
        request,
        payload={"confirmation": "RUN SUNDAY REVIEW"},
    )
    lets_begin_payload = web.console_lets_begin(
        request,
        payload={
            "confirmation": "BEGIN STRENGTH TEST",
            "start_date": "2026-05-18",
            "start_date_confirmation": "2026-05-18",
        },
    )

    assert review_payload == {
        "status": "queued",
        "command": "sunday_review",
        "job_id": "review-job-test",
        "status_url": "/console/jobs/review-job-test",
        "status_api_url": "/console/jobs/review-job-test/status",
        "workflow": "scripts.run_sunday_review",
    }
    assert lets_begin_payload == {
        "status": "queued",
        "command": "lets_begin",
        "job_id": "lets-begin-job-test",
        "status_url": "/console/jobs/lets-begin-job-test",
        "status_api_url": "/console/jobs/lets-begin-job-test/status",
        "workflow": "pete lets-begin",
        "start_date": "2026-05-18",
    }
    assert job_service.enqueued[0]["operation"] == "sunday_review"
    assert job_service.enqueued[0]["command"][-2:] == ["-m", "scripts.run_sunday_review"]
    assert job_service.enqueued[0]["request_summary"] == {"workflow": "scripts.run_sunday_review"}
    assert job_service.enqueued[1]["operation"] == "lets_begin"
    assert job_service.enqueued[1]["command"] == ["pete", "lets-begin", "--start-date", "2026-05-18"]
    assert job_service.enqueued[1]["request_summary"] == {
        "workflow": "pete lets-begin",
        "start_date": "2026-05-18",
    }
    assert [event["outcome"] for event in audit_events] == ["started", "succeeded", "started", "succeeded"]


def test_console_lets_begin_requires_start_date_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    csrf_token = dependencies.generate_csrf_token(service.token)
    audit_events: list[dict] = []
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    monkeypatch.setattr(dependencies, "prepare_job_context", lambda request, operation: "lets-begin-confirm-job")
    monkeypatch.setattr(dependencies, "audit_command_event", lambda request, **event: audit_events.append(event))

    with pytest.raises(web.HTTPException) as exc:
        web.console_lets_begin(
            _Request(
                path="/console/operations/lets-begin",
                method="POST",
                headers={dependencies.CSRF_HEADER_NAME: csrf_token, "X-Request-ID": "req-lets-confirm"},
                cookies={
                    dependencies.session_cookie_name(): service.token,
                    dependencies.csrf_cookie_name(): csrf_token,
                },
            ),
            payload={
                "confirmation": "BEGIN STRENGTH TEST",
                "start_date": "2026-05-18",
                "start_date_confirmation": "2026-05-19",
            },
        )

    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "start_date_confirmation_required"
    assert exc.value.detail["expected_start_date"] == "2026-05-18"
    assert exc.value.detail["job_id"] == "lets-begin-confirm-job"
    assert exc.value.detail["request_id"] == "req-lets-confirm"
    assert audit_events[-1]["command"] == "lets_begin"
    assert audit_events[-1]["outcome"] == "confirmation_failed"


def test_console_lets_begin_rejects_invalid_start_date(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    csrf_token = dependencies.generate_csrf_token(service.token)
    audit_events: list[dict] = []
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    monkeypatch.setattr(dependencies, "prepare_job_context", lambda request, operation: "lets-begin-invalid-date-job")
    monkeypatch.setattr(dependencies, "audit_command_event", lambda request, **event: audit_events.append(event))

    with pytest.raises(web.HTTPException) as exc:
        web.console_lets_begin(
            _Request(
                path="/console/operations/lets-begin",
                method="POST",
                headers={dependencies.CSRF_HEADER_NAME: csrf_token, "X-Request-ID": "req-lets-invalid"},
                cookies={
                    dependencies.session_cookie_name(): service.token,
                    dependencies.csrf_cookie_name(): csrf_token,
                },
            ),
            payload={
                "confirmation": "BEGIN STRENGTH TEST",
                "start_date": "18/05/2026",
                "start_date_confirmation": "18/05/2026",
            },
        )

    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "invalid_date"
    assert exc.value.detail["field"] == "start_date"
    assert exc.value.detail["job_id"] == "lets-begin-invalid-date-job"
    assert exc.value.detail["request_id"] == "req-lets-invalid"
    assert audit_events[-1]["command"] == "lets_begin"
    assert audit_events[-1]["outcome"] == "failed"


def test_console_sunday_review_requires_operator_csrf(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    audit_events: list[dict] = []
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    monkeypatch.setattr(dependencies, "audit_command_event", lambda request, **event: audit_events.append(event))

    with pytest.raises(web.HTTPException) as exc:
        web.console_run_sunday_review(
            _Request(
                path="/console/operations/run-sunday-review",
                method="POST",
                cookies={dependencies.session_cookie_name(): service.token},
            ),
            payload={"confirmation": "RUN SUNDAY REVIEW"},
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "csrf_required"
    assert audit_events[-1]["command"] == "sunday_review"
    assert audit_events[-1]["outcome"] == "authorization_denied"


@pytest.mark.parametrize(
    ("handler", "command", "payload"),
    [
        (web.console_run_sunday_review, "sunday_review", {"confirmation": "RUN SUNDAY REVIEW"}),
        (
            web.console_lets_begin,
            "lets_begin",
            {
                "confirmation": "BEGIN STRENGTH TEST",
                "start_date": "2026-05-18",
                "start_date_confirmation": "2026-05-18",
            },
        ),
    ],
)
def test_weekly_lifecycle_commands_require_operator_role(
    monkeypatch: pytest.MonkeyPatch,
    handler,
    command: str,
    payload: dict,
) -> None:
    service = _UserService(_user(ROLE_READ_ONLY))
    csrf_token = dependencies.generate_csrf_token(service.token)
    audit_events: list[dict] = []
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    monkeypatch.setattr(dependencies, "audit_command_event", lambda request, **event: audit_events.append(event))

    with pytest.raises(web.HTTPException) as exc:
        handler(
            _Request(
                path=f"/console/operations/{command}",
                method="POST",
                headers={dependencies.CSRF_HEADER_NAME: csrf_token},
                cookies={
                    dependencies.session_cookie_name(): service.token,
                    dependencies.csrf_cookie_name(): csrf_token,
                },
            ),
            payload=payload,
        )

    assert exc.value.status_code == 403
    assert audit_events[-1]["command"] == command
    assert audit_events[-1]["outcome"] == "authorization_denied"


@pytest.mark.parametrize(
    ("message_type", "expected_text"),
    [
        ("summary", "Daily summary preview text"),
        ("trainer", "Trainer check-in preview text"),
        ("plan", "Weekly plan preview text"),
    ],
)
def test_console_message_preview_generates_without_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    message_type: str,
    expected_text: str,
) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    csrf_token = dependencies.generate_csrf_token(service.token)
    job_service = _JobService()
    audit_events: list[dict] = []
    captured: dict[str, object] = {}

    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    monkeypatch.setattr(dependencies, "enforce_command_rate_limit", lambda request, command: None)
    monkeypatch.setattr(dependencies, "prepare_job_context", lambda request, operation: f"{message_type}-preview-job")
    monkeypatch.setattr(dependencies, "get_job_service", lambda: job_service)
    monkeypatch.setattr(
        dependencies,
        "audit_command_event",
        lambda request, **event: audit_events.append(event),
    )
    monkeypatch.setattr(web, "_build_console_message_orchestrator", lambda: object())

    def _build_message_text(selected_type: str, *, orchestrator=None) -> str:
        captured["message_type"] = selected_type
        captured["orchestrator"] = orchestrator
        return expected_text

    monkeypatch.setattr(web, "_build_console_message_text", _build_message_text)

    payload = web.console_preview_message(
        _Request(
            path="/console/operations/preview-message",
            method="POST",
            headers={dependencies.CSRF_HEADER_NAME: csrf_token, "X-Request-ID": f"req-{message_type}-preview"},
            cookies={
                dependencies.session_cookie_name(): service.token,
                dependencies.csrf_cookie_name(): csrf_token,
            },
        ),
        payload={"message_type": message_type},
    )

    assert captured["message_type"] == message_type
    assert captured["orchestrator"] is not None
    assert payload["status"] == "completed"
    assert payload["command"] == "message_preview"
    assert payload["message_type"] == message_type
    assert payload["message"] == expected_text
    assert payload["job_id"] == f"{message_type}-preview-job"
    assert payload["request_id"] == f"req-{message_type}-preview"
    assert job_service.enqueued[0]["operation"] == "message_preview"
    assert job_service.enqueued[0]["request_summary"] == {"message_type": message_type, "send": False}
    assert [event["outcome"] for event in audit_events] == ["started", "succeeded"]
    assert audit_events[-1]["summary"]["message"] is None
    assert audit_events[-1]["summary"]["message_length"] == len(expected_text)


def test_console_message_preview_requires_operator_csrf(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    audit_events: list[dict] = []
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    monkeypatch.setattr(
        dependencies,
        "audit_command_event",
        lambda request, **event: audit_events.append(event),
    )

    with pytest.raises(web.HTTPException) as exc:
        web.console_preview_message(
            _Request(
                path="/console/operations/preview-message",
                method="POST",
                cookies={dependencies.session_cookie_name(): service.token},
            ),
            payload={"message_type": "summary"},
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "csrf_required"
    assert audit_events[-1]["command"] == "message_preview"
    assert audit_events[-1]["outcome"] == "authorization_denied"


@pytest.mark.parametrize("message_type", ["summary", "trainer", "plan"])
def test_console_message_resend_send_paths_are_confirmed_job_tracked_and_audited(
    monkeypatch: pytest.MonkeyPatch,
    message_type: str,
) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    csrf_token = dependencies.generate_csrf_token(service.token)
    job_service = _JobService()
    audit_events: list[dict] = []
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    monkeypatch.setattr(dependencies, "enforce_command_rate_limit", lambda request, command: None)
    monkeypatch.setattr(dependencies, "prepare_job_context", lambda request, operation: f"{message_type}-send-job")
    monkeypatch.setattr(dependencies, "get_job_service", lambda: job_service)
    monkeypatch.setattr(
        dependencies,
        "audit_command_event",
        lambda request, **event: audit_events.append(event),
    )

    payload = web.console_resend_message(
        _Request(
            path="/console/operations/resend-message",
            method="POST",
            headers={dependencies.CSRF_HEADER_NAME: csrf_token, "X-Request-ID": f"req-{message_type}-send"},
            cookies={
                dependencies.session_cookie_name(): service.token,
                dependencies.csrf_cookie_name(): csrf_token,
            },
        ),
        payload={"confirmation": "RESEND MESSAGE", "message_type": message_type},
    )

    assert payload == {
        "status": "queued",
        "command": "message_resend",
        "job_id": f"{message_type}-send-job",
        "status_url": f"/console/jobs/{message_type}-send-job",
        "status_api_url": f"/console/jobs/{message_type}-send-job/status",
        "message_type": message_type,
    }
    assert job_service.enqueued[0]["operation"] == "message_resend"
    assert job_service.enqueued[0]["command"] == ["pete", "message", f"--{message_type}", "--send"]
    assert job_service.enqueued[0]["request_summary"] == {"message_type": message_type}
    assert job_service.enqueued[0]["requester"].username == "pete"
    assert job_service.enqueued[0]["request_id"] == f"req-{message_type}-send"
    assert [event["outcome"] for event in audit_events] == ["started", "succeeded"]


def test_console_morning_report_preview_generates_without_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    csrf_token = dependencies.generate_csrf_token(service.token)
    job_service = _JobService()
    captured: dict[str, object] = {}

    class _MorningReportOrchestrator:
        def get_daily_summary(self, target_date=None):
            captured["target_date"] = target_date
            return "Morning report text"

        def send_telegram_message(self, message: str) -> bool:
            captured["sent"] = message
            return True

    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    monkeypatch.setattr(dependencies, "enforce_command_rate_limit", lambda request, command: None)
    monkeypatch.setattr(dependencies, "audit_command_event", lambda request, **event: None)
    monkeypatch.setattr(dependencies, "prepare_job_context", lambda request, operation: "morning-preview-job")
    monkeypatch.setattr(dependencies, "get_job_service", lambda: job_service)
    monkeypatch.setattr(web, "_build_morning_report_orchestrator", lambda: _MorningReportOrchestrator())

    payload = web.console_preview_morning_report(
        _Request(
            path="/console/operations/morning-report-preview",
            method="POST",
            headers={dependencies.CSRF_HEADER_NAME: csrf_token, "X-Request-ID": "req-morning-preview"},
            cookies={
                dependencies.session_cookie_name(): service.token,
                dependencies.csrf_cookie_name(): csrf_token,
            },
        ),
        payload={"target_date": "2026-05-15"},
    )

    assert captured["target_date"] == date(2026, 5, 15)
    assert "sent" not in captured
    assert payload["status"] == "completed"
    assert payload["report"] == "Morning report text"
    assert payload["sent"] is False
    assert payload["job_id"] == "morning-preview-job"
    assert payload["request_id"] == "req-morning-preview"
    assert job_service.enqueued[0]["operation"] == "morning_report_preview"
    assert job_service.enqueued[0]["request_summary"] == {"target_date": "2026-05-15", "send": False}


def test_console_morning_report_send_requires_confirmation_and_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    csrf_token = dependencies.generate_csrf_token(service.token)
    job_service = _JobService()
    captured: dict[str, object] = {}

    class _MorningReportOrchestrator:
        def get_daily_summary(self, target_date=None):
            captured["target_date"] = target_date
            return "Morning report to send"

        def send_telegram_message(self, message: str) -> bool:
            captured["sent"] = message
            return True

    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    monkeypatch.setattr(dependencies, "enforce_command_rate_limit", lambda request, command: None)
    monkeypatch.setattr(dependencies, "audit_command_event", lambda request, **event: None)
    monkeypatch.setattr(dependencies, "prepare_job_context", lambda request, operation: "morning-send-job")
    monkeypatch.setattr(dependencies, "get_job_service", lambda: job_service)
    monkeypatch.setattr(web, "_build_morning_report_orchestrator", lambda: _MorningReportOrchestrator())

    payload = web.console_send_morning_report(
        _Request(
            path="/console/operations/morning-report-send",
            method="POST",
            headers={dependencies.CSRF_HEADER_NAME: csrf_token, "X-Request-ID": "req-morning-send"},
            cookies={
                dependencies.session_cookie_name(): service.token,
                dependencies.csrf_cookie_name(): csrf_token,
            },
        ),
        payload={"confirmation": "SEND MORNING REPORT"},
    )

    assert captured["target_date"] is None
    assert captured["sent"] == "Morning report to send"
    assert payload["sent"] is True
    assert payload["summary"] == "Morning report sent."
    assert payload["job_id"] == "morning-send-job"
    assert job_service.enqueued[0]["operation"] == "morning_report_send"
    assert job_service.enqueued[0]["request_summary"] == {"target_date": None, "send": True}


def test_console_morning_report_rejects_invalid_date(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    csrf_token = dependencies.generate_csrf_token(service.token)
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    monkeypatch.setattr(dependencies, "prepare_job_context", lambda request, operation: "morning-invalid-date-job")
    monkeypatch.setattr(dependencies, "audit_command_event", lambda request, **event: None)

    with pytest.raises(web.HTTPException) as exc:
        web.console_preview_morning_report(
            _Request(
                path="/console/operations/morning-report-preview",
                method="POST",
                headers={dependencies.CSRF_HEADER_NAME: csrf_token, "X-Request-ID": "req-morning-invalid-date"},
                cookies={
                    dependencies.session_cookie_name(): service.token,
                    dependencies.csrf_cookie_name(): csrf_token,
                },
            ),
            payload={"target_date": "15/05/2026"},
        )

    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "invalid_date"
    assert exc.value.detail["field"] == "target_date"
    assert exc.value.detail["job_id"] == "morning-invalid-date-job"
    assert exc.value.detail["request_id"] == "req-morning-invalid-date"


def test_console_morning_report_failure_includes_request_and_job_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    csrf_token = dependencies.generate_csrf_token(service.token)
    job_service = _JobService()

    class _FailingMorningReportOrchestrator:
        def get_daily_summary(self, target_date=None):
            raise RuntimeError("narrative builder failed")

    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    monkeypatch.setattr(dependencies, "enforce_command_rate_limit", lambda request, command: None)
    monkeypatch.setattr(dependencies, "audit_command_event", lambda request, **event: None)
    monkeypatch.setattr(dependencies, "prepare_job_context", lambda request, operation: "morning-failure-job")
    monkeypatch.setattr(dependencies, "get_job_service", lambda: job_service)
    monkeypatch.setattr(web, "_build_morning_report_orchestrator", lambda: _FailingMorningReportOrchestrator())

    with pytest.raises(web.HTTPException) as exc:
        web.console_preview_morning_report(
            _Request(
                path="/console/operations/morning-report-preview",
                method="POST",
                headers={dependencies.CSRF_HEADER_NAME: csrf_token, "X-Request-ID": "req-morning-failure"},
                cookies={
                    dependencies.session_cookie_name(): service.token,
                    dependencies.csrf_cookie_name(): csrf_token,
                },
            ),
            payload={},
        )

    assert exc.value.status_code == 500
    assert exc.value.detail["code"] == "morning_report_preview_failed"
    assert exc.value.detail["message"] == "narrative builder failed"
    assert exc.value.detail["job_id"] == "morning-failure-job"
    assert exc.value.detail["request_id"] == "req-morning-failure"


def test_web_routes_are_mounted_once_outside_api_v1_namespace() -> None:
    mounted_routes = {
        (method, route.path)
        for route in getattr(api.app, "routes", [])
        for method in getattr(route, "methods", set())
    }

    assert ("GET", "/console/status") in mounted_routes
    assert ("GET", "/console/logs") in mounted_routes
    assert ("GET", "/console/jobs") in mounted_routes
    assert ("GET", "/console/jobs/{job_id}/status") in mounted_routes
    assert ("GET", "/console/history") in mounted_routes
    assert ("GET", "/console/history.json") in mounted_routes
    assert ("POST", "/console/operations/run-sync") in mounted_routes
    assert ("POST", "/console/operations/run-withings-sync") in mounted_routes
    assert ("POST", "/console/operations/ingest-apple") in mounted_routes
    assert ("POST", "/console/operations/run-sunday-review") in mounted_routes
    assert ("POST", "/console/operations/lets-begin") in mounted_routes
    assert ("POST", "/console/operations/preview-message") in mounted_routes
    assert ("POST", "/console/operations/morning-report-preview") in mounted_routes
    assert ("POST", "/console/operations/morning-report-send") in mounted_routes
    assert ("GET", "/console/alerts") in mounted_routes
    assert ("GET", "/console/scheduler") in mounted_routes
    assert ("POST", "/console/nutrition/logs") in mounted_routes
    assert ("GET", "/console/security") in mounted_routes
    assert ("POST", "/console/security/mfa/start") in mounted_routes
    assert ("POST", "/console/security/mfa/confirm") in mounted_routes
    assert ("POST", "/console/admin/users") in mounted_routes
    assert ("GET", "/login") in mounted_routes
    assert ("GET", f"{api.API_V1_PREFIX}/console/status") not in mounted_routes
