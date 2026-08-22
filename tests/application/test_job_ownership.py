from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
import subprocess
import sys
import threading

import pytest

from pete_e.application import jobs
from pete_e.domain.jobs import ApplicationJob, ApplicationOperationLock


class _Clock:
    def __init__(self) -> None:
        self._now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
        self._lock = threading.Lock()

    def __call__(self) -> datetime:
        with self._lock:
            return self._now

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._now += timedelta(seconds=seconds)


class _FencedRepository:
    def __init__(self, clock: _Clock) -> None:
        self.clock = clock
        self.jobs: dict[str, ApplicationJob] = {}
        self.operation_lock: ApplicationOperationLock | None = None
        self._mutex = threading.Lock()
        self._heartbeat_condition = threading.Condition(self._mutex)
        self._heartbeat_counts: dict[str, int] = {}
        self._completed: dict[str, threading.Event] = {}
        self.recovered = threading.Event()

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
            created_at=self.clock(),
        )
        with self._mutex:
            self.jobs[job.id] = job
            self._completed[job.id] = threading.Event()
        return job

    def claim(self, job_id: str, *, worker_id: str, lease_seconds: float):
        with self._mutex:
            current = self.jobs[job_id]
            expired = (
                current.status == "running"
                and current.lease_expires_at is not None
                and current.lease_expires_at < self.clock()
            )
            if current.status != "queued" and not expired:
                return None
            claimed = replace(
                current,
                status="running",
                started_at=current.started_at or self.clock(),
                worker_id=worker_id,
                ownership_token=(current.ownership_token or 0) + 1,
                attempt_number=current.attempt_number + (1 if expired else 0),
                last_heartbeat_at=self.clock(),
                lease_expires_at=self.clock() + timedelta(seconds=lease_seconds),
                abandon_reason=None,
            )
            self.jobs[job_id] = claimed
            return claimed

    def handoff_claim(
        self,
        job_id: str,
        *,
        from_worker_id: str,
        from_ownership_token: int,
        to_worker_id: str,
        lease_seconds: float,
    ):
        with self._mutex:
            current = self.jobs[job_id]
            operation_lock = self.operation_lock
            if not self._owns(current, from_worker_id, from_ownership_token):
                return None
            if (current.progress_summary or {}).get("phase") != "dispatching":
                return None
            if not self._lock_owned(operation_lock, job_id, from_worker_id, from_ownership_token):
                return None
            transferred = replace(
                current,
                worker_id=to_worker_id,
                ownership_token=from_ownership_token + 1,
                last_heartbeat_at=self.clock(),
                lease_expires_at=self.clock() + timedelta(seconds=lease_seconds),
                progress_summary={**(current.progress_summary or {}), "phase": "running"},
            )
            self.jobs[job_id] = transferred
            self.operation_lock = replace(
                operation_lock,
                worker_id=to_worker_id,
                ownership_token=transferred.ownership_token,
                expires_at=transferred.lease_expires_at,
            )
            return transferred

    def heartbeat(
        self,
        *,
        job_id: str,
        worker_id: str,
        ownership_token: int,
        lease_seconds: float,
        progress=None,
    ) -> bool:
        with self._heartbeat_condition:
            current = self.jobs[job_id]
            if not self._owns(current, worker_id, ownership_token):
                return False
            if not self._lock_owned(self.operation_lock, job_id, worker_id, ownership_token):
                return False
            lease_expires_at = self.clock() + timedelta(seconds=lease_seconds)
            self.jobs[job_id] = replace(
                current,
                last_heartbeat_at=self.clock(),
                lease_expires_at=lease_expires_at,
                progress_summary=progress,
            )
            self.operation_lock = replace(self.operation_lock, expires_at=lease_expires_at)
            self._heartbeat_counts[job_id] = self._heartbeat_counts.get(job_id, 0) + 1
            self._heartbeat_condition.notify_all()
            return True

    def complete(
        self,
        job_id: str,
        *,
        worker_id: str,
        ownership_token: int,
        require_lock: bool = True,
        **values,
    ) -> bool:
        with self._mutex:
            current = self.jobs[job_id]
            if not self._owns(current, worker_id, ownership_token):
                return False
            self.jobs[job_id] = replace(current, **values)
            owns_lock = self._lock_owned(self.operation_lock, job_id, worker_id, ownership_token)
            if require_lock and not owns_lock:
                return False
            if owns_lock:
                self.operation_lock = None
            self._completed[job_id].set()
            return True

    def acquire_high_risk_operation_lock(
        self,
        *,
        operation: str,
        job_id: str,
        worker_id: str,
        ownership_token: int,
        lease_seconds: float,
    ):
        with self._mutex:
            current = self.jobs[job_id]
            if not self._owns(current, worker_id, ownership_token):
                return None
            if self.operation_lock is not None and self._lock_is_active(self.operation_lock):
                return None
            self.operation_lock = ApplicationOperationLock(
                lock_name="high_risk_operation",
                operation=operation,
                job_id=job_id,
                worker_id=worker_id,
                ownership_token=ownership_token,
                acquired_at=self.clock(),
                expires_at=self.clock() + timedelta(seconds=lease_seconds),
            )
            return self.operation_lock

    def release_high_risk_operation_lock(
        self,
        *,
        job_id: str,
        worker_id: str,
        ownership_token: int,
    ) -> bool:
        with self._mutex:
            if not self._lock_owned(self.operation_lock, job_id, worker_id, ownership_token):
                return False
            self.operation_lock = None
            return True

    def get_active_high_risk_operation_lock(self):
        with self._mutex:
            if self.operation_lock is not None and not self._lock_is_active(self.operation_lock):
                self.operation_lock = None
            return self.operation_lock

    def recover_stale_operations(self, *, stale_before: datetime, queued_before: datetime) -> int:
        recovered = 0
        with self._mutex:
            for job_id, current in list(self.jobs.items()):
                expired_running = (
                    current.status == "running"
                    and current.lease_expires_at is not None
                    and current.lease_expires_at < stale_before
                )
                stale_queued = current.status == "queued" and current.created_at < queued_before
                if expired_running or stale_queued:
                    self.jobs[job_id] = replace(
                        current,
                        status="abandoned",
                        completed_at=self.clock(),
                        abandon_reason="lease_expired",
                        failure_reason="lease_expired",
                    )
                    recovered += 1
            if self.operation_lock is not None and not self._lock_is_active(self.operation_lock):
                self.operation_lock = None
            if recovered:
                self.recovered.set()
        return recovered

    def get(self, job_id: str):
        with self._mutex:
            return self.jobs.get(job_id)

    def list_recent(self, *, limit: int = 25):
        with self._mutex:
            return list(self.jobs.values())[:limit]

    def list_current(self, *, limit: int = 10):
        return [job for job in self.list_recent(limit=limit) if not job.is_terminal]

    def wait_for_heartbeats(self, job_id: str, count: int, timeout: float = 1.0) -> bool:
        with self._heartbeat_condition:
            return self._heartbeat_condition.wait_for(
                lambda: self._heartbeat_counts.get(job_id, 0) >= count,
                timeout=timeout,
            )

    def heartbeat_count(self, job_id: str) -> int:
        with self._mutex:
            return self._heartbeat_counts.get(job_id, 0)

    def wait_for_completion(self, job_id: str, timeout: float = 1.0) -> bool:
        return self._completed[job_id].wait(timeout)

    def _owns(self, job: ApplicationJob, worker_id: str, ownership_token: int) -> bool:
        return (
            job.status == "running"
            and job.worker_id == worker_id
            and job.ownership_token == ownership_token
            and job.lease_expires_at is not None
            and job.lease_expires_at >= self.clock()
        )

    @staticmethod
    def _lock_owned(operation_lock, job_id: str, worker_id: str, ownership_token: int) -> bool:
        return (
            operation_lock is not None
            and operation_lock.job_id == job_id
            and operation_lock.worker_id == worker_id
            and operation_lock.ownership_token == ownership_token
        )

    def _lock_is_active(self, operation_lock: ApplicationOperationLock) -> bool:
        current = self.jobs.get(str(operation_lock.job_id))
        return (
            current is not None
            and self._owns(
                current,
                str(operation_lock.worker_id),
                int(operation_lock.ownership_token or 0),
            )
            and operation_lock.expires_at is not None
            and operation_lock.expires_at >= self.clock()
        )


def _create(repo: _FencedRepository, job_id: str, operation: str = "sync") -> ApplicationJob:
    return repo.create(
        job_id=job_id,
        operation=operation,
        requester_user_id=None,
        requester_username=None,
        auth_scheme="test",
        request_id=job_id,
        correlation_id=job_id,
        request_summary={},
    )


def test_state_machine_claim_heartbeat_completion_failure_and_lease_loss() -> None:
    clock = _Clock()
    repo = _FencedRepository(clock)
    queued = _create(repo, "state-success")
    claim = repo.claim(queued.id, worker_id="worker-a", lease_seconds=10)
    assert claim is not None and claim.ownership_token == 1
    assert repo.acquire_high_risk_operation_lock(
        operation="sync",
        job_id=claim.id,
        worker_id="worker-a",
        ownership_token=1,
        lease_seconds=10,
    )
    assert repo.heartbeat(
        job_id=claim.id,
        worker_id="worker-a",
        ownership_token=1,
        lease_seconds=10,
        progress={"phase": "halfway"},
    )
    assert repo.complete(
        claim.id,
        worker_id="worker-a",
        ownership_token=1,
        status="succeeded",
        completed_at=clock(),
    )
    assert repo.get(claim.id).status == "succeeded"
    assert repo.operation_lock is None
    assert not repo.heartbeat(
        job_id=claim.id,
        worker_id="worker-a",
        ownership_token=1,
        lease_seconds=10,
    )

    failed = _create(repo, "state-failure")
    failed_claim = repo.claim(failed.id, worker_id="worker-a", lease_seconds=10)
    assert failed_claim is not None
    assert repo.acquire_high_risk_operation_lock(
        operation="sync",
        job_id=failed.id,
        worker_id="worker-a",
        ownership_token=1,
        lease_seconds=10,
    )
    assert repo.complete(
        failed.id,
        worker_id="worker-a",
        ownership_token=1,
        status="failed",
        completed_at=clock(),
        failure_reason="controlled failure",
    )
    assert repo.get(failed.id).status == "failed"


def test_stale_worker_cannot_complete_fail_or_release_reowned_job() -> None:
    clock = _Clock()
    repo = _FencedRepository(clock)
    job = _create(repo, "reowned")
    old = repo.claim(job.id, worker_id="worker-old", lease_seconds=1)
    assert old is not None
    assert repo.acquire_high_risk_operation_lock(
        operation="sync",
        job_id=job.id,
        worker_id="worker-old",
        ownership_token=1,
        lease_seconds=1,
    )
    clock.advance(2)
    new = repo.claim(job.id, worker_id="worker-new", lease_seconds=10)
    assert new is not None and new.ownership_token == 2
    assert repo.acquire_high_risk_operation_lock(
        operation="sync",
        job_id=job.id,
        worker_id="worker-new",
        ownership_token=2,
        lease_seconds=10,
    )

    for attempted_status in ("succeeded", "failed"):
        assert not repo.complete(
            job.id,
            worker_id="worker-old",
            ownership_token=1,
            status=attempted_status,
            completed_at=clock(),
        )
    assert not repo.release_high_risk_operation_lock(
        job_id=job.id,
        worker_id="worker-old",
        ownership_token=1,
    )
    assert repo.get(job.id).worker_id == "worker-new"
    assert repo.operation_lock is not None
    assert repo.operation_lock.ownership_token == 2


def test_two_workers_short_lease_long_callback_heartbeats_and_rejects_overlap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(jobs.observability, "record_job_completed", lambda **_kwargs: None)
    monkeypatch.setattr(jobs.alerts, "record_operation_outcome", lambda **_kwargs: None)
    clock = _Clock()
    repo = _FencedRepository(clock)
    callback_entered = threading.Event()
    callback_release = threading.Event()
    first = jobs.ApplicationJobService(
        repo,
        lease_seconds=0.09,
        heartbeat_interval_seconds=0.01,
        clock=clock,
        start_recovery=False,
    )
    second = jobs.ApplicationJobService(
        repo,
        lease_seconds=0.09,
        heartbeat_interval_seconds=0.01,
        clock=clock,
        start_recovery=False,
    )
    try:
        first.enqueue_callback(
            job_id="long-callback",
            operation="sync",
            callback=lambda: (callback_entered.set(), callback_release.wait(1))[1],
            requester=None,
            request_id="long-callback",
            correlation_id="long-callback",
            request_summary={},
            timeout_seconds=None,
        )
        assert callback_entered.wait(1)
        assert repo.wait_for_heartbeats("long-callback", 2)
        next_heartbeat = repo.heartbeat_count("long-callback") + 1
        clock.advance(0.05)
        assert repo.wait_for_heartbeats("long-callback", next_heartbeat)
        clock.advance(0.05)
        assert second.recover_stale_operations() == 0

        with pytest.raises(jobs.HTTPException) as conflict:
            second.run_callback(
                job_id="overlap",
                operation="plan",
                callback=lambda: None,
                requester=None,
                request_id="overlap",
                correlation_id="overlap",
                request_summary={},
                timeout_seconds=None,
            )
        assert conflict.value.status_code == 409
        assert repo.get("long-callback").status == "running"
        assert first.worker_id != second.worker_id

        callback_release.set()
        assert repo.wait_for_completion("long-callback")
        assert repo.get("long-callback").status == "succeeded"
    finally:
        callback_release.set()
        first.close(wait=True)
        second.close(wait=True)


def test_periodic_recovery_runs_after_expiry_without_another_initialization() -> None:
    clock = _Clock()
    repo = _FencedRepository(clock)
    service = jobs.ApplicationJobService(
        repo,
        lease_seconds=0.06,
        recovery_interval_seconds=0.01,
        clock=clock,
    )
    try:
        job = _create(repo, "periodic")
        claim = repo.claim(job.id, worker_id="crashed-worker", lease_seconds=0.06)
        assert claim is not None
        assert repo.acquire_high_risk_operation_lock(
            operation="sync",
            job_id=job.id,
            worker_id="crashed-worker",
            ownership_token=1,
            lease_seconds=0.06,
        )
        clock.advance(1)
        assert repo.recovered.wait(1)
        assert repo.get(job.id).status == "abandoned"
        assert repo.operation_lock is None
    finally:
        service.close(wait=True)


def test_callback_and_subprocess_both_heartbeat_for_entire_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(jobs.observability, "record_job_completed", lambda **_kwargs: None)
    monkeypatch.setattr(jobs.alerts, "record_operation_outcome", lambda **_kwargs: None)

    callback_clock = _Clock()
    callback_repo = _FencedRepository(callback_clock)
    callback_release = threading.Event()
    callback_service = jobs.ApplicationJobService(
        callback_repo,
        lease_seconds=0.09,
        heartbeat_interval_seconds=0.01,
        clock=callback_clock,
        start_recovery=False,
    )
    callback_service.enqueue_callback(
        job_id="callback-parity",
        operation="sync",
        callback=lambda: callback_release.wait(1),
        requester=None,
        request_id="callback-parity",
        correlation_id="callback-parity",
        request_summary={},
        timeout_seconds=None,
    )
    assert callback_repo.wait_for_heartbeats("callback-parity", 1)
    callback_release.set()
    assert callback_repo.wait_for_completion("callback-parity")
    callback_service.close(wait=True)

    process_clock = _Clock()
    process_repo = _FencedRepository(process_clock)
    process_release = threading.Event()

    class _Process:
        returncode = 0

        def communicate(self, timeout=None):
            process_release.wait(1)
            return ("done", "")

        def terminate(self):
            process_release.set()

    monkeypatch.setattr(jobs.subprocess, "Popen", lambda *_args, **_kwargs: _Process())
    process_service = jobs.ApplicationJobService(
        process_repo,
        lease_seconds=0.09,
        heartbeat_interval_seconds=0.01,
        clock=process_clock,
        start_recovery=False,
    )
    process_service.enqueue_subprocess(
        job_id="subprocess-parity",
        operation="plan",
        command=["controlled-process"],
        requester=None,
        request_id="subprocess-parity",
        correlation_id="subprocess-parity",
        request_summary={},
        timeout_seconds=None,
    )
    assert process_repo.wait_for_heartbeats("subprocess-parity", 1)
    process_release.set()
    assert process_repo.wait_for_completion("subprocess-parity")
    process_service.close(wait=True)


def test_external_dispatch_heartbeats_until_the_helper_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatch_entered = threading.Event()
    dispatch_release = threading.Event()

    class _DispatchResult:
        returncode = 0
        stdout = "queued"
        stderr = ""

    def _controlled_dispatch(*_args, **_kwargs):
        dispatch_entered.set()
        dispatch_release.wait(1)
        return _DispatchResult()

    monkeypatch.setattr(jobs.subprocess, "run", _controlled_dispatch)
    clock = _Clock()
    repo = _FencedRepository(clock)
    service = jobs.ApplicationJobService(
        repo,
        lease_seconds=0.09,
        heartbeat_interval_seconds=0.01,
        clock=clock,
        start_recovery=False,
    )
    dispatch_thread = threading.Thread(
        target=lambda: service.dispatch_external(
            job_id="dispatch-heartbeat",
            operation="deploy",
            dispatch_command=["controlled-systemd-dispatch", "dispatch-heartbeat"],
            requester=None,
            request_id="dispatch-heartbeat",
            correlation_id="dispatch-heartbeat",
            request_summary={},
        ),
        daemon=True,
    )
    try:
        dispatch_thread.start()
        assert dispatch_entered.wait(1)
        assert repo.wait_for_heartbeats("dispatch-heartbeat", 2)
        assert repo.get("dispatch-heartbeat").progress_summary["phase"] == "dispatching"
    finally:
        dispatch_release.set()
        dispatch_thread.join(timeout=1)
        current = repo.get("dispatch-heartbeat")
        if current is not None and current.status == "running":
            service._complete_claim(
                current,
                status="failed",
                exit_code=None,
                result_summary="test cleanup",
                stdout_summary=None,
                stderr_summary=None,
                failure_reason="test cleanup",
            )
        service.close(wait=True)


def test_worker_ids_are_unique_across_instances_and_processes() -> None:
    local_ids = {jobs.generate_worker_id(), jobs.generate_worker_id()}
    child_environment = os.environ.copy()
    for name in (
        "WITHINGS_CLIENT_ID",
        "WITHINGS_CLIENT_SECRET",
        "WITHINGS_REDIRECT_URI",
        "WITHINGS_REFRESH_TOKEN",
        "DROPBOX_APP_KEY",
        "DROPBOX_APP_SECRET",
        "DROPBOX_REFRESH_TOKEN",
    ):
        child_environment[name] = "test-placeholder"
    child_id = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "from pete_e.application.jobs import generate_worker_id; print(generate_worker_id())",
        ],
        text=True,
        env=child_environment,
    ).strip()
    assert len(local_ids) == 2
    assert child_id not in local_ids
    assert ":pid-" in child_id


def test_independent_worker_handoff_reaches_terminal_state_after_dispatcher_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(jobs.observability, "record_job_completed", lambda **_kwargs: None)
    monkeypatch.setattr(jobs.alerts, "record_operation_outcome", lambda **_kwargs: None)

    class _DispatchResult:
        returncode = 0
        stdout = "queued"
        stderr = ""

    monkeypatch.setattr(jobs.subprocess, "run", lambda *_args, **_kwargs: _DispatchResult())
    clock = _Clock()
    repo = _FencedRepository(clock)
    dispatcher = jobs.ApplicationJobService(
        repo,
        worker_id="api-dispatcher",
        lease_seconds=1,
        heartbeat_interval_seconds=0.1,
        clock=clock,
        start_recovery=False,
    )
    dispatcher.dispatch_external(
        job_id="deploy-restart",
        operation="deploy",
        dispatch_command=["controlled-systemd-dispatch", "deploy-restart"],
        requester=None,
        request_id="deploy-restart",
        correlation_id="deploy-restart",
        request_summary={"commit_sha": "a" * 40, "ref": "refs/heads/main"},
    )
    dispatched = repo.get("deploy-restart")
    assert dispatched.status == "running"
    assert dispatched.ownership_token == 1

    process_entered = threading.Event()
    process_release = threading.Event()

    class _DeployProcess:
        returncode = 0

        def communicate(self, timeout=None):
            process_entered.set()
            process_release.wait(1)
            return ("deployment complete", "")

        def terminate(self):
            process_release.set()

    monkeypatch.setattr(jobs.subprocess, "Popen", lambda *_args, **_kwargs: _DeployProcess())
    deployment_worker = jobs.ApplicationJobService(
        repo,
        worker_id="independent-systemd-worker",
        lease_seconds=1,
        heartbeat_interval_seconds=0.1,
        clock=clock,
        start_recovery=False,
    )
    worker_result: list[bool] = []
    worker_thread = threading.Thread(
        target=lambda: worker_result.append(
            deployment_worker.run_handed_off_subprocess(
                job_id="deploy-restart",
                command=["controlled-deploy-script"],
                timeout_seconds=None,
            )
        ),
        daemon=True,
    )
    worker_thread.start()
    assert process_entered.wait(1)
    assert repo.get("deploy-restart").ownership_token == 2
    assert (
        repo.handoff_claim(
            "deploy-restart",
            from_worker_id="independent-systemd-worker",
            from_ownership_token=2,
            to_worker_id="duplicate-systemd-worker",
            lease_seconds=1,
        )
        is None
    )

    # Simulate the API service being stopped while the separate unit continues.
    dispatcher.close(wait=False)
    process_release.set()
    assert repo.wait_for_completion("deploy-restart")
    worker_thread.join(timeout=1)
    deployment_worker.close(wait=True)

    terminal = repo.get("deploy-restart")
    assert worker_result == [True]
    assert terminal.status == "succeeded"
    assert terminal.worker_id == "independent-systemd-worker"
    assert terminal.ownership_token == 2
    assert repo.operation_lock is None
