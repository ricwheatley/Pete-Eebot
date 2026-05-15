from __future__ import annotations

import threading
import time
from datetime import datetime
from types import SimpleNamespace

import pytest

from pete_e.application import jobs
from pete_e.application.concurrency_guard import high_risk_operation_guard
from pete_e.domain.auth import AuthUser, ROLE_OPERATOR
from pete_e.domain.jobs import ApplicationJob


class _Repo:
    def __init__(self) -> None:
        self.jobs: dict[str, ApplicationJob] = {}
        self.command_events: list[dict] = []
        self.completed = threading.Event()

    def create(self, **kwargs) -> ApplicationJob:
        job = ApplicationJob(
            id=kwargs["job_id"],
            operation=kwargs["operation"],
            requester_user_id=kwargs["requester_user_id"],
            requester_username=kwargs["requester_username"],
            status="queued",
            request_id=kwargs["request_id"],
            correlation_id=kwargs["correlation_id"],
            request_summary=kwargs["request_summary"],
            created_at=datetime(2026, 5, 15, 9, 0),
        )
        self.jobs[job.id] = job
        return job

    def mark_running(self, job_id: str, *, started_at: datetime) -> None:
        current = self.jobs[job_id]
        self.jobs[job_id] = ApplicationJob(
            **{**current.__dict__, "status": "running", "started_at": started_at}
        )

    def complete(self, job_id: str, **kwargs) -> None:
        current = self.jobs[job_id]
        self.jobs[job_id] = ApplicationJob(**{**current.__dict__, **kwargs})
        self.completed.set()

    def get(self, job_id: str):
        return self.jobs.get(job_id)

    def list_recent(self, *, limit: int = 25):
        return list(self.jobs.values())[:limit]

    def record_command_event(self, **kwargs):
        self.command_events.append(kwargs)
        return SimpleNamespace(**kwargs)

    def list_command_history(self, **kwargs):
        return [SimpleNamespace(**event) for event in self.command_events]


class _LockingRepo(_Repo):
    def __init__(self) -> None:
        super().__init__()
        self.active_lock = None

    def acquire_high_risk_operation_lock(self, *, operation: str, job_id: str, lease_seconds: float):
        if self.active_lock is not None:
            return None
        self.active_lock = SimpleNamespace(operation=operation, job_id=job_id)
        return self.active_lock

    def release_high_risk_operation_lock(self, *, job_id: str) -> None:
        if self.active_lock is not None and self.active_lock.job_id == job_id:
            self.active_lock = None

    def get_active_high_risk_operation_lock(self):
        return self.active_lock

    def list_current(self, *, limit: int = 10):
        return [job for job in self.jobs.values() if not job.is_terminal][:limit]


def _release_guard() -> None:
    while high_risk_operation_guard.active_operation is not None:
        high_risk_operation_guard.release()


def _wait_for_guard_release(timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while high_risk_operation_guard.active_operation is not None:
        if time.monotonic() >= deadline:
            raise AssertionError("guard did not release")
        time.sleep(0.01)


def test_application_job_service_captures_safe_subprocess_output(monkeypatch) -> None:
    _release_guard()
    repo = _Repo()
    service = jobs.ApplicationJobService(repo)

    class _Process:
        returncode = 0

        def communicate(self, timeout=None):
            return ("created plan token=secret-value", "api_key=hidden")

    monkeypatch.setattr(jobs.subprocess, "Popen", lambda *args, **kwargs: _Process())
    monkeypatch.setattr(jobs.observability, "record_job_completed", lambda **kwargs: None)
    monkeypatch.setattr(jobs.alerts, "record_operation_outcome", lambda **kwargs: None)

    service.enqueue_subprocess(
        job_id="plan-job-safe-output",
        operation="plan",
        command=["pete", "plan"],
        requester=AuthUser(
            id=1,
            username="pete",
            email=None,
            display_name=None,
            roles=(ROLE_OPERATOR,),
            is_active=True,
        ),
        request_id="req-1",
        correlation_id="req-1",
        request_summary={"weeks": 4},
        timeout_seconds=30,
    )

    assert repo.completed.wait(timeout=1)
    job = repo.get("plan-job-safe-output")
    assert job.status == "succeeded"
    assert job.exit_code == 0
    assert job.requester_username == "pete"
    assert job.stdout_summary == "created plan token=<redacted>"
    assert job.stderr_summary == "api_key=<redacted>"
    _wait_for_guard_release()


def test_application_job_service_records_sanitized_command_history() -> None:
    repo = _Repo()
    service = jobs.ApplicationJobService(repo)
    requester = AuthUser(
        id=1,
        username="pete",
        email=None,
        display_name=None,
        roles=(ROLE_OPERATOR,),
        is_active=True,
    )

    service.record_command_event(
        request_id="req-history",
        correlation_id="req-history",
        job_id="sync-job",
        requester=requester,
        auth_scheme="session",
        command="sync",
        outcome="started",
        summary={"days": 3, "api_key": "hidden", "nested": {"token": "secret-value"}},
        client_identity="127.0.0.1",
    )

    event = repo.command_events[0]
    assert event["request_id"] == "req-history"
    assert event["job_id"] == "sync-job"
    assert event["requester_username"] == "pete"
    assert event["auth_scheme"] == "session"
    assert event["command"] == "sync"
    assert event["outcome"] == "started"
    assert event["safe_summary"] == {"days": 3, "api_key": "<redacted>", "nested": {"token": "<redacted>"}}


def test_application_job_service_records_nonzero_exit(monkeypatch) -> None:
    _release_guard()
    repo = _Repo()
    service = jobs.ApplicationJobService(repo)

    class _Process:
        returncode = 2

        def communicate(self, timeout=None):
            return ("", "bad plan")

    monkeypatch.setattr(jobs.subprocess, "Popen", lambda *args, **kwargs: _Process())
    monkeypatch.setattr(jobs.observability, "record_job_completed", lambda **kwargs: None)
    monkeypatch.setattr(jobs.alerts, "record_operation_outcome", lambda **kwargs: None)

    service.enqueue_subprocess(
        job_id="plan-job-failed",
        operation="plan",
        command=["pete", "plan"],
        requester=None,
        request_id="req-2",
        correlation_id="req-2",
        request_summary={},
        timeout_seconds=30,
    )

    assert repo.completed.wait(timeout=1)
    job = repo.get("plan-job-failed")
    assert job.status == "failed"
    assert job.exit_code == 2
    assert job.stderr_summary == "bad plan"
    assert job.failure_reason == "Process exited with code 2."
    _wait_for_guard_release()


def test_application_job_service_runs_sync_callback_under_repository_lock(monkeypatch) -> None:
    repo = _LockingRepo()
    service = jobs.ApplicationJobService(repo)
    monkeypatch.setattr(jobs.observability, "record_job_completed", lambda **kwargs: None)
    monkeypatch.setattr(jobs.alerts, "record_operation_outcome", lambda **kwargs: None)

    result = service.run_callback(
        job_id="sync-job-1",
        operation="sync",
        callback=lambda: SimpleNamespace(success=True, summary_line=lambda days: f"synced {days} days"),
        requester=None,
        request_id="req-sync",
        correlation_id="req-sync",
        request_summary={"days": 3},
        timeout_seconds=30,
        result_summary_builder=lambda sync_result: sync_result.summary_line(days=3),
    )

    assert result.success is True
    job = repo.get("sync-job-1")
    assert job.status == "succeeded"
    assert job.result_summary == "synced 3 days"
    assert repo.active_lock is None


def test_application_job_service_rejects_overlap_from_repository_lock(monkeypatch) -> None:
    repo = _LockingRepo()
    repo.active_lock = SimpleNamespace(operation="plan", job_id="plan-job")
    service = jobs.ApplicationJobService(repo)
    monkeypatch.setattr(jobs.observability, "record_job_completed", lambda **kwargs: None)
    monkeypatch.setattr(jobs.alerts, "record_operation_outcome", lambda **kwargs: None)

    with pytest.raises(jobs.HTTPException) as exc:
        service.run_callback(
            job_id="sync-job-conflict",
            operation="sync",
            callback=lambda: None,
            requester=None,
            request_id="req-sync",
            correlation_id="req-sync",
            request_summary={},
            timeout_seconds=30,
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["requested_operation"] == "sync"
    assert exc.value.detail["active_operation"] == "plan"
    assert repo.get("sync-job-conflict").status == "failed"
