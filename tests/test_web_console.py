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
    assert "Resend Message" in html
    assert "RUN SYNC" in html
    assert "RUN WITHINGS SYNC" in html
    assert "RUN APPLE INGEST" in html
    assert "GENERATE PLAN" in html
    assert "RESEND MESSAGE" in html
    assert 'data-endpoint="/console/operations/run-sync"' in html
    assert 'data-endpoint="/console/operations/run-withings-sync"' in html
    assert 'data-endpoint="/console/operations/ingest-apple"' in html


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
    assert ("GET", "/login") in mounted_routes
    assert ("GET", f"{api.API_V1_PREFIX}/console/status") not in mounted_routes
