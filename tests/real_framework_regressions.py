"""Focused end-to-end regressions using the installed framework stack."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import date, datetime
from importlib.metadata import version
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace


_TEST_ENV = {
    "USER_DATE_OF_BIRTH": "1990-01-01",
    "USER_HEIGHT_CM": "180",
    "USER_GOAL_WEIGHT_KG": "80",
    "TELEGRAM_TOKEN": "dummy",
    "TELEGRAM_CHAT_ID": "123456",
    "WITHINGS_CLIENT_ID": "",
    "WITHINGS_CLIENT_SECRET": "",
    "WITHINGS_REDIRECT_URI": "",
    "WITHINGS_REFRESH_TOKEN": "",
    "WGER_API_KEY": "dummy",
    "DROPBOX_HEALTH_METRICS_DIR": "/health",
    "DROPBOX_WORKOUTS_DIR": "/workouts",
    "DROPBOX_APP_KEY": "",
    "DROPBOX_APP_SECRET": "",
    "DROPBOX_REFRESH_TOKEN": "",
    "APPLE_MAX_STALE_DAYS": "3",
    "WITHINGS_ALERT_REAUTH": "true",
    "POSTGRES_USER": "postgres",
    "POSTGRES_PASSWORD": "postgres",
    "POSTGRES_HOST": "127.0.0.1",
    "POSTGRES_PORT": "1",
    "POSTGRES_DB": "pete_e_test_unreachable",
    "DATABASE_URL": "postgresql://pete_test:pete_test@127.0.0.1:1/pete_e_test_unreachable",
    "PETEEEBOT_ENV_FILE": str(Path(__file__).resolve().parents[1] / ".pytest-no-env"),
    "PETE_LOG_TO_CONSOLE": "false",
}
os.environ.update(_TEST_ENV)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import fastapi  # noqa: E402
import tenacity  # noqa: E402
import typer  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from pete_e.api_errors import install_api_error_handlers  # noqa: E402
from pete_e.api_routes import dependencies, plan, web  # noqa: E402
from pete_e.application import jobs, sync  # noqa: E402
from pete_e.application.orchestrator import Orchestrator  # noqa: E402
from pete_e.cli import messenger as cli  # noqa: E402
from pete_e.domain.auth import AuthUser, ROLE_OPERATOR  # noqa: E402
from pete_e.domain.jobs import ApplicationJob  # noqa: E402


class _JobRepository:
    def __init__(self) -> None:
        self.jobs: dict[str, ApplicationJob] = {}
        self.active_lock = None
        self._mutex = threading.Lock()

    def create(self, **values) -> ApplicationJob:
        job = ApplicationJob(
            id=values["job_id"],
            operation=values["operation"],
            requester_user_id=values["requester_user_id"],
            requester_username=values["requester_username"],
            auth_scheme=values["auth_scheme"],
            status="queued",
            request_id=values["request_id"],
            correlation_id=values["correlation_id"],
            request_summary=values["request_summary"],
            created_at=datetime.now(),
        )
        with self._mutex:
            self.jobs[job.id] = job
        return job

    def mark_running(self, job_id: str, *, started_at: datetime) -> None:
        with self._mutex:
            current = self.jobs[job_id]
            self.jobs[job_id] = ApplicationJob(
                **{**current.__dict__, "status": "running", "started_at": started_at}
            )

    def complete(self, job_id: str, **values) -> None:
        with self._mutex:
            current = self.jobs[job_id]
            self.jobs[job_id] = ApplicationJob(**{**current.__dict__, **values})

    def get(self, job_id: str) -> ApplicationJob | None:
        with self._mutex:
            return self.jobs.get(job_id)

    def list_recent(self, *, limit: int = 25) -> list[ApplicationJob]:
        with self._mutex:
            return list(self.jobs.values())[:limit]

    def list_current(self, *, limit: int = 10) -> list[ApplicationJob]:
        return [job for job in self.list_recent(limit=limit) if not job.is_terminal]

    def acquire_high_risk_operation_lock(
        self,
        *,
        operation: str,
        job_id: str,
        lease_seconds: float,  # noqa: ARG002
    ):
        with self._mutex:
            if self.active_lock is not None:
                return None
            self.active_lock = SimpleNamespace(operation=operation, job_id=job_id)
            return self.active_lock

    def release_high_risk_operation_lock(self, *, job_id: str) -> None:
        with self._mutex:
            if self.active_lock is not None and self.active_lock.job_id == job_id:
                self.active_lock = None

    def get_active_high_risk_operation_lock(self):
        with self._mutex:
            return self.active_lock


def _wait_for_terminal(repository: _JobRepository, job_id: str) -> ApplicationJob:
    completed = threading.Event()
    for _ in range(400):
        job = repository.get(job_id)
        if (
            job is not None
            and job.is_terminal
            and repository.get_active_high_risk_operation_lock() is None
        ):
            return job
        completed.wait(0.005)
    raise AssertionError(f"job {job_id} did not reach a terminal state")


def _operator() -> AuthUser:
    return AuthUser(
        id=1,
        username="operator",
        email=None,
        display_name="Operator",
        roles=(ROLE_OPERATOR,),
        is_active=True,
    )


def _exercise_plan_http_and_job_path() -> dict[str, object]:
    repository = _JobRepository()
    job_service = jobs.ApplicationJobService(repository)
    process_payloads: list[dict[str, object]] = []
    generated: list[date] = []
    exported: list[dict[str, object]] = []

    class _PlanPort:
        def create_next_plan_for_cycle(self, *, start_date: date) -> int:
            generated.append(start_date)
            return 84

    class _ExportPort:
        def export_plan_week(self, **values) -> None:
            exported.append(values)

    class _Process:
        def __init__(self, command: list[str], **kwargs) -> None:  # noqa: ARG002
            self.command = command
            self.returncode: int | None = None

        def communicate(self, timeout=None):  # noqa: ARG002
            weeks = int(self.command[self.command.index("--weeks") + 1])
            start_date = date.fromisoformat(
                self.command[self.command.index("--start-date") + 1]
            )
            process_payloads.append(
                {"command": list(self.command), "weeks": weeks, "start_date": start_date.isoformat()}
            )
            orchestrator = Orchestrator.__new__(Orchestrator)
            orchestrator.dal = SimpleNamespace(hold_plan_generation_lock=lambda: nullcontext())
            orchestrator.plan_service = _PlanPort()
            orchestrator.export_service = _ExportPort()
            try:
                plan_id = orchestrator.generate_and_deploy_next_plan(
                    start_date=start_date,
                    weeks=weeks,
                )
            except Exception as exc:  # pragma: no cover - assertion output for a regression.
                self.returncode = 2
                return "", f"{type(exc).__name__}: {exc}"
            self.returncode = 0
            return f"created plan {plan_id}", ""

    jobs.subprocess.Popen = _Process
    job_metrics: list[dict[str, object]] = []
    job_alerts: list[dict[str, object]] = []
    jobs.observability.record_job_completed = lambda **values: job_metrics.append(values)
    jobs.alerts.record_operation_outcome = lambda **values: job_alerts.append(values) or True

    job_ids = iter(("api-default", "api-explicit", "web-default"))
    plan.validate_api_key = lambda *args, **kwargs: None
    plan.enforce_command_rate_limit = lambda *args, **kwargs: None
    plan.audit_command_event = lambda *args, **kwargs: None
    plan.prepare_job_context = lambda *args, **kwargs: next(job_ids)
    plan.get_job_service = lambda: job_service

    dependencies.enforce_command_rate_limit = lambda *args, **kwargs: None
    dependencies.audit_command_event = lambda *args, **kwargs: None
    dependencies.prepare_job_context = lambda *args, **kwargs: next(job_ids)
    dependencies.get_job_service = lambda: job_service
    web.require_browser_user = lambda request: _operator()
    web.require_role = lambda *args, **kwargs: _operator()
    web._operator_today = lambda: date(2026, 8, 24)

    app = FastAPI()
    install_api_error_handlers(app)
    app.include_router(plan.router)
    app.include_router(web.router)

    with TestClient(app) as client:
        schema = app.openapi()
        weeks_parameter = next(
            item
            for item in schema["paths"]["/run_pete_plan_async"]["post"]["parameters"]
            if item["name"] == "weeks"
        )
        assert weeks_parameter["schema"]["default"] == 4
        assert weeks_parameter["schema"]["enum"] == [4]

        api_default_response = client.post(
            "/run_pete_plan_async",
            params={"start_date": "2026-08-24"},
        )
        assert api_default_response.status_code == 200
        assert api_default_response.json()["weeks"] == 4
        api_default_job = _wait_for_terminal(repository, "api-default")
        assert api_default_job.status == "succeeded"
        assert api_default_job.request_summary["weeks"] == 4

        api_explicit_response = client.post(
            "/run_pete_plan_async",
            params={"weeks": 4, "start_date": "2026-08-31"},
        )
        assert api_explicit_response.status_code == 200
        api_explicit_job = _wait_for_terminal(repository, "api-explicit")
        assert api_explicit_job.status == "succeeded"
        assert api_explicit_job.request_summary["weeks"] == 4

        jobs_before_invalid_api = len(repository.jobs)
        invalid_api_response = client.post(
            "/run_pete_plan_async",
            params={"weeks": 1, "start_date": "2026-09-07"},
        )
        assert invalid_api_response.status_code == 400
        assert invalid_api_response.json()["error"]["code"] == "unsupported_plan_duration"
        assert len(repository.jobs) == jobs_before_invalid_api

        operations_response = client.get("/console/operations")
        assert operations_response.status_code == 200
        operations_html = operations_response.text
        assert "fixed 4-week 5/3/1 block" in operations_html
        assert 'name="weeks"' in operations_html
        assert 'value="4"' in operations_html
        assert 'min="4"' in operations_html
        assert 'max="4"' in operations_html
        assert "readonly" in operations_html

        web_default_response = client.post(
            "/console/operations/generate-plan",
            json={"confirmation": "GENERATE PLAN", "start_date": "2026-09-14"},
        )
        assert web_default_response.status_code == 200
        assert web_default_response.json()["weeks"] == 4
        web_default_job = _wait_for_terminal(repository, "web-default")
        assert web_default_job.status == "succeeded"
        assert web_default_job.request_summary["weeks"] == 4

        jobs_before_invalid_web = len(repository.jobs)
        invalid_web_response = client.post(
            "/console/operations/generate-plan",
            json={
                "confirmation": "GENERATE PLAN",
                "weeks": 12,
                "start_date": "2026-09-21",
            },
        )
        assert invalid_web_response.status_code == 400
        assert invalid_web_response.json()["error"]["code"] == "unsupported_plan_duration"
        assert len(repository.jobs) == jobs_before_invalid_web

        fractional_web_response = client.post(
            "/console/operations/generate-plan",
            json={
                "confirmation": "GENERATE PLAN",
                "weeks": 4.5,
                "start_date": "2026-09-21",
            },
        )
        assert fractional_web_response.status_code == 400
        assert fractional_web_response.json()["error"]["code"] == "bad_request"
        assert len(repository.jobs) == jobs_before_invalid_web

    assert [payload["weeks"] for payload in process_payloads] == [4, 4, 4]
    assert len(generated) == 3
    assert len(exported) == 3
    assert [item["outcome"] for item in job_metrics] == ["succeeded"] * 3
    assert [item["outcome"] for item in job_alerts] == ["succeeded"] * 3
    return {
        "api_default_terminal": api_default_job.status,
        "api_explicit_terminal": api_explicit_job.status,
        "web_default_terminal": web_default_job.status,
        "serialized_weeks": [payload["weeks"] for payload in process_payloads],
    }


def _exercise_real_cli() -> dict[str, object]:
    calls: list[dict[str, object]] = []
    build_calls = 0

    class _CliOrchestrator:
        def generate_and_deploy_next_plan(self, *, start_date: date, weeks: int) -> int:
            calls.append({"start_date": start_date.isoformat(), "weeks": weeks})
            return 91

        def close(self) -> None:
            return None

    def _build_cli_orchestrator() -> _CliOrchestrator:
        nonlocal build_calls
        build_calls += 1
        return _CliOrchestrator()

    cli._build_orchestrator = _build_cli_orchestrator
    runner = CliRunner()
    help_result = runner.invoke(cli.app, ["plan", "--help"], color=False)
    assert help_result.exit_code == 0
    assert "fixed 4-week" in help_result.stdout
    assert "[default: 4]" in help_result.stdout
    assert "4<=x<=4" in help_result.stdout

    default_result = runner.invoke(
        cli.app,
        ["plan", "--start-date", "2026-08-24"],
        color=False,
    )
    assert default_result.exit_code == 0, default_result.stdout
    assert calls == [{"start_date": "2026-08-24", "weeks": 4}]

    invalid_result = runner.invoke(
        cli.app,
        ["plan", "--weeks", "1", "--start-date", "2026-08-24"],
        color=False,
    )
    assert invalid_result.exit_code == 2
    assert "not in the range 4<=x<=4" in invalid_result.stdout
    assert build_calls == 1
    return {"default_weeks": calls[0]["weeks"], "invalid_exit_code": invalid_result.exit_code}


def _exercise_real_tenacity() -> dict[str, object]:
    retry_metrics: list[dict[str, object]] = []
    logs: list[dict[str, object]] = []
    sync.observability.record_job_retry = lambda **values: retry_metrics.append(values)
    sync.log_utils.log_message = lambda message, level="INFO", **values: logs.append(
        {"message": message, "level": level, **values}
    )

    immediate = sync._run_with_retry(
        execute=lambda: (True, [], {"Withings": "ok"}, []),
        max_attempts=3,
        base_delay=0,
        label="Sync",
        summary_name="daily",
    )
    assert immediate == sync.SyncResult(
        success=True,
        attempts=1,
        failed_sources=[],
        source_statuses={"Withings": "ok"},
        label="daily",
        undelivered_alerts=[],
    )
    assert retry_metrics == []

    responses = iter(
        (
            (False, ["Withings"], {"Withings": "failed"}, ["first alert"]),
            (True, [], {"Withings": "ok"}, []),
        )
    )
    after_retry = sync._run_with_retry(
        execute=lambda: next(responses),
        max_attempts=3,
        base_delay=0,
        label="Sync",
        summary_name="daily",
    )
    assert after_retry == sync.SyncResult(
        success=True,
        attempts=2,
        failed_sources=[],
        source_statuses={"Withings": "ok"},
        label="daily",
        undelivered_alerts=[],
    )
    assert retry_metrics == [{"operation": "daily", "source": "Withings"}]

    retry_metrics.clear()
    logs.clear()
    structured_exhaustion = sync._run_with_retry(
        execute=lambda: (
            False,
            ["Withings"],
            {"AppleDropbox": "ok", "Withings": "failed"},
            ["Reauthorize Withings"],
        ),
        max_attempts=3,
        base_delay=0,
        label="Sync",
        summary_name="daily",
    )
    assert structured_exhaustion == sync.SyncResult(
        success=False,
        attempts=3,
        failed_sources=["Withings"],
        source_statuses={"AppleDropbox": "ok", "Withings": "failed"},
        label="daily",
        undelivered_alerts=["Reauthorize Withings"],
    )
    assert retry_metrics == [
        {"operation": "daily", "source": "Withings"},
        {"operation": "daily", "source": "Withings"},
    ]
    assert len([entry for entry in logs if entry["level"] == "ERROR"]) == 1

    retry_metrics.clear()
    logs.clear()
    cause = RuntimeError("provider offline")
    calls = 0

    def _raise_provider_failure():
        nonlocal calls
        calls += 1
        raise cause

    repository = _JobRepository()
    job_service = jobs.ApplicationJobService(repository)
    completion_metrics: list[dict[str, object]] = []
    operation_alerts: list[dict[str, object]] = []
    jobs.observability.record_job_completed = lambda **values: completion_metrics.append(values)
    jobs.alerts.record_operation_outcome = lambda **values: operation_alerts.append(values) or True
    exhausted = job_service.run_callback(
        job_id="sync-exhausted",
        operation="sync",
        callback=lambda: sync._run_with_retry(
            execute=_raise_provider_failure,
            max_attempts=3,
            base_delay=0,
            label="Sync",
            summary_name="daily",
        ),
        requester=None,
        request_id="request-sync-exhausted",
        correlation_id="request-sync-exhausted",
        request_summary={"days": 1, "retries": 3},
        timeout_seconds=30,
        result_summary_builder=lambda result: result.summary_line(days=1),
    )
    assert exhausted == sync.SyncResult(
        success=False,
        attempts=3,
        failed_sources=["provider offline"],
        source_statuses={},
        label="daily",
        undelivered_alerts=[],
    )
    assert calls == 3
    assert retry_metrics == [
        {"operation": "daily", "source": "exception"},
        {"operation": "daily", "source": "exception"},
    ]
    final_errors = [
        entry
        for entry in logs
        if entry["level"] == "ERROR" and entry["message"].startswith("All 3 Sync attempts")
    ]
    final_job_logs = [
        entry
        for entry in logs
        if entry["level"] == "ERROR" and entry["message"] == "job sync failed"
    ]
    assert len(final_errors) == 1
    assert len(final_job_logs) == 1
    assert final_errors[0]["exc_info"][1] is cause
    assert repository.get("sync-exhausted").status == "failed"
    assert len(completion_metrics) == 1
    assert completion_metrics[0]["operation"] == "sync"
    assert completion_metrics[0]["outcome"] == "failed"
    assert len(operation_alerts) == 1
    assert operation_alerts[0]["operation"] == "sync"
    assert operation_alerts[0]["outcome"] == "failed"
    return {
        "immediate_attempts": immediate.attempts,
        "recovered_attempts": after_retry.attempts,
        "structured_exhausted_attempts": structured_exhaustion.attempts,
        "exception_exhausted_attempts": exhausted.attempts,
        "exception_job_terminal": repository.get("sync-exhausted").status,
        "final_error_logs": len(final_errors),
        "final_job_logs": len(final_job_logs),
        "final_job_metrics": len(completion_metrics),
    }


def main() -> None:
    module_files = {
        "fastapi": str(Path(fastapi.__file__).resolve()),
        "typer": str(Path(typer.__file__).resolve()),
        "tenacity": str(Path(tenacity.__file__).resolve()),
    }
    tests_dir = Path(__file__).resolve().parent
    assert all(tests_dir not in Path(path).parents for path in module_files.values())
    payload = {
        "versions": {
            "fastapi": version("fastapi"),
            "starlette": version("starlette"),
            "typer": version("typer"),
            "click": version("click"),
            "tenacity": version("tenacity"),
        },
        "module_files": module_files,
        "plan_http_job": _exercise_plan_http_and_job_path(),
        "cli": _exercise_real_cli(),
        "sync_retry": _exercise_real_tenacity(),
    }
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
