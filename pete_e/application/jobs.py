from __future__ import annotations

import contextvars
import concurrent.futures
from datetime import datetime, timedelta, timezone
import os
import re
import socket
import subprocess
import threading
import time
import uuid
from typing import Any, Mapping, Protocol

from fastapi import HTTPException

from pete_e.application import alerts
from pete_e.application.concurrency_guard import OperationInProgress, high_risk_operation_guard
from pete_e import observability
from pete_e.domain.auth import AuthUser
from pete_e.domain.jobs import (
    ApplicationJob,
    CommandHistoryEntry,
    JOB_STATUS_FAILED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
    JOB_STATUS_TIMEOUT,
)
from pete_e.infrastructure import log_utils
from pete_e.logging_setup import bind_log_context, reset_log_context


class ApplicationJobRepository(Protocol):
    def create(
        self,
        *,
        job_id: str,
        operation: str,
        requester_user_id: int | None,
        requester_username: str | None,
        auth_scheme: str | None,
        request_id: str,
        correlation_id: str,
        request_summary: dict[str, Any],
    ) -> ApplicationJob: ...

    def claim(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_seconds: float,
    ) -> ApplicationJob | None: ...

    def handoff_claim(
        self,
        job_id: str,
        *,
        from_worker_id: str,
        from_ownership_token: int,
        to_worker_id: str,
        lease_seconds: float,
    ) -> ApplicationJob | None: ...

    def heartbeat(
        self,
        *,
        job_id: str,
        worker_id: str,
        ownership_token: int,
        lease_seconds: float,
        progress: dict[str, Any] | None = None,
    ) -> bool: ...

    def complete(
        self,
        job_id: str,
        *,
        worker_id: str,
        ownership_token: int,
        require_lock: bool,
        status: str,
        completed_at: datetime,
        exit_code: int | None,
        result_summary: str | None,
        stdout_summary: str | None,
        stderr_summary: str | None,
        failure_reason: str | None,
    ) -> bool: ...

    def get(self, job_id: str) -> ApplicationJob | None: ...

    def list_recent(self, *, limit: int = 25) -> list[ApplicationJob]: ...

    def list_current(self, *, limit: int = 10) -> list[ApplicationJob]: ...

    def record_command_event(
        self,
        *,
        request_id: str,
        correlation_id: str,
        job_id: str | None,
        requester_user_id: int | None,
        requester_username: str | None,
        auth_scheme: str | None,
        command: str,
        outcome: str,
        safe_summary: dict[str, Any],
        client_identity: str | None,
    ) -> CommandHistoryEntry: ...

    def list_command_history(
        self,
        *,
        limit: int = 25,
        query: str | None = None,
        command: str | None = None,
        outcome: str | None = None,
    ) -> list[CommandHistoryEntry]: ...

    def acquire_high_risk_operation_lock(
        self,
        *,
        operation: str,
        job_id: str,
        worker_id: str,
        ownership_token: int,
        lease_seconds: float,
    ) -> object | None: ...

    def release_high_risk_operation_lock(
        self,
        *,
        job_id: str,
        worker_id: str,
        ownership_token: int,
    ) -> bool: ...

    def get_active_high_risk_operation_lock(self) -> object | None: ...


_SECRET_PATTERN = re.compile(r"(?i)(token|secret|password|api[_-]?key)=([^\s]+)")
_SECRET_KEY_PATTERN = re.compile(r"(?i)(token|secret|password|api[_-]?key|authorization|cookie)")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def generate_worker_id(*, role: str = "application") -> str:
    """Return a process/restart-unique, operator-readable worker identity."""

    host = socket.gethostname().strip() or "unknown-host"
    return f"{host}:{role}:pid-{os.getpid()}:{uuid.uuid4().hex}"


class JobOwnershipLost(RuntimeError):
    """Raised when an execution can no longer mutate its fenced job."""


def _safe_output_summary(value: str | bytes | None, *, limit: int = 12000) -> str | None:
    if value is None:
        return None
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    text = _SECRET_PATTERN.sub(r"\1=<redacted>", text)
    text = "".join(ch if ch == "\n" or ch == "\t" or ord(ch) >= 32 else " " for ch in text)
    text = text.strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    return f"...{text[-limit:]}"


def _safe_summary_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        return "<truncated>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _safe_output_summary(value, limit=2000)
    if isinstance(value, bytes):
        return _safe_output_summary(value, limit=2000)
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, nested_value in list(value.items())[:50]:
            key_text = str(key)
            if _SECRET_KEY_PATTERN.search(key_text):
                sanitized[key_text] = "<redacted>"
            else:
                sanitized[key_text] = _safe_summary_value(nested_value, depth=depth + 1)
        return sanitized
    if isinstance(value, (list, tuple, set)):
        return [_safe_summary_value(item, depth=depth + 1) for item in list(value)[:50]]
    return _safe_output_summary(str(value), limit=2000)


def safe_summary(summary: Mapping[str, Any] | None) -> dict[str, Any]:
    value = _safe_summary_value(dict(summary or {}))
    return value if isinstance(value, dict) else {}


def _operation_conflict(exc: OperationInProgress) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "operation_in_progress",
            "message": str(exc),
            "requested_operation": exc.requested_operation,
            "active_operation": exc.active_operation,
        },
    )


def _log_job_event(
    *,
    operation: str,
    job_id: str,
    outcome: str,
    level: str = "INFO",
    summary: dict[str, Any] | None = None,
) -> None:
    log_utils.log_event(
        event="application_job",
        message=f"job {operation} {outcome}",
        tag="JOB",
        level=level,
        operation=operation,
        job_id=job_id,
        outcome=outcome,
        summary=summary or {},
    )


class ApplicationJobService:
    def __init__(
        self,
        repository: ApplicationJobRepository,
        *,
        worker_id: str | None = None,
        lease_seconds: float = 300.0,
        heartbeat_interval_seconds: float | None = None,
        recovery_interval_seconds: float | None = None,
        clock=_utcnow,
        start_recovery: bool = True,
    ) -> None:
        self.repository = repository
        self._worker_id = worker_id or generate_worker_id()
        self._lease_seconds = max(0.03, float(lease_seconds))
        default_heartbeat = self._lease_seconds / 3
        requested_heartbeat = float(heartbeat_interval_seconds or default_heartbeat)
        if requested_heartbeat <= 0 or requested_heartbeat >= self._lease_seconds / 2:
            raise ValueError("heartbeat interval must be positive and less than half the job lease")
        self._heartbeat_interval_seconds = max(0.01, requested_heartbeat)
        self._recovery_interval_seconds = max(
            0.01,
            float(recovery_interval_seconds or min(60.0, self._lease_seconds / 2)),
        )
        self._clock = clock
        self._closed = threading.Event()
        self._recovery_stop = threading.Event()
        self._recovery_thread: threading.Thread | None = None
        self._active_processes: dict[str, subprocess.Popen] = {}
        self._active_processes_lock = threading.Lock()
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="application-job",
        )
        if start_recovery:
            self._recovery_thread = threading.Thread(
                target=self._recovery_loop,
                name=f"job-recovery-{self._worker_id[-8:]}",
                daemon=True,
            )
            self._recovery_thread.start()

    @property
    def worker_id(self) -> str:
        return self._worker_id

    def close(self, *, wait: bool = False) -> None:
        """Stop admission/recovery and terminate owned subprocesses.

        Callback jobs cannot be force-cancelled safely. With ``wait=False`` they
        may drain while this process remains alive; if the process exits, their
        leases expire and another worker's recovery fences their late writes.
        """

        if self._closed.is_set():
            return
        self._closed.set()
        self._recovery_stop.set()
        if self._recovery_thread is not None:
            self._recovery_thread.join(timeout=1.0)
        with self._active_processes_lock:
            processes = list(self._active_processes.values())
        for process in processes:
            terminate = getattr(process, "terminate", None)
            if callable(terminate):
                try:
                    terminate()
                except Exception:
                    pass
        self._executor.shutdown(wait=wait, cancel_futures=True)

    def _ensure_open(self) -> None:
        if self._closed.is_set():
            raise RuntimeError("Application job service is shutting down")

    def _active_operation_from_repository(self) -> str | None:
        active_loader = getattr(self.repository, "get_active_high_risk_operation_lock", None)
        if not callable(active_loader):
            return high_risk_operation_guard.active_operation
        active_lock = active_loader()
        return str(getattr(active_lock, "operation", "") or "") or None

    def _acquire_operation_lock(self, operation: str, claim: ApplicationJob) -> None:
        acquire = getattr(self.repository, "acquire_high_risk_operation_lock", None)
        if not callable(acquire):
            high_risk_operation_guard.acquire(operation)
            return
        lock = acquire(
            operation=operation,
            job_id=claim.id,
            worker_id=str(claim.worker_id),
            ownership_token=int(claim.ownership_token or 0),
            lease_seconds=self._lease_seconds,
        )
        if lock is None:
            raise OperationInProgress(
                requested_operation=operation,
                active_operation=self._active_operation_from_repository(),
            )

    def _release_operation_lock(self, claim: ApplicationJob) -> None:
        release = getattr(self.repository, "release_high_risk_operation_lock", None)
        if callable(release):
            release(
                job_id=claim.id,
                worker_id=str(claim.worker_id),
                ownership_token=int(claim.ownership_token or 0),
            )
            return
        high_risk_operation_guard.release()

    def recover_stale_operations(self) -> int:
        recover = getattr(self.repository, "recover_stale_operations", None)
        if not callable(recover):
            return 0
        now = self._clock()
        recovered = int(
            recover(
                stale_before=now,
                queued_before=now - timedelta(seconds=self._lease_seconds),
            )
        )
        if recovered:
            log_utils.log_event(
                event="application_job_recovery",
                message="recovered stale application jobs",
                tag="JOB",
                level="WARNING",
                worker_id=self._worker_id,
                recovered_count=recovered,
            )
        return recovered

    def _recovery_loop(self) -> None:
        while not self._recovery_stop.is_set():
            try:
                self.recover_stale_operations()
            except Exception as exc:
                log_utils.log_event(
                    event="application_job_recovery",
                    message="application job recovery pass failed",
                    tag="JOB",
                    level="ERROR",
                    worker_id=self._worker_id,
                    error_type=type(exc).__name__,
                )
            self._recovery_stop.wait(self._recovery_interval_seconds)

    def _create_job(
        self,
        *,
        job_id: str,
        operation: str,
        requester: AuthUser | None,
        request_id: str,
        correlation_id: str,
        request_summary: dict[str, Any],
        auth_scheme: str | None = None,
    ) -> ApplicationJob:
        self._ensure_open()
        return self.repository.create(
            job_id=job_id,
            operation=operation,
            requester_user_id=requester.id if requester is not None else None,
            requester_username=requester.username if requester is not None else None,
            auth_scheme=auth_scheme,
            request_id=request_id,
            correlation_id=correlation_id,
            request_summary=safe_summary(request_summary),
        )

    def _claim_job(self, job: ApplicationJob) -> ApplicationJob:
        claim = self.repository.claim(
            job.id,
            worker_id=self._worker_id,
            lease_seconds=self._lease_seconds,
        )
        if claim is None or claim.ownership_token is None:
            raise JobOwnershipLost(f"Job {job.id} could not be claimed")
        _log_job_event(
            operation=job.operation,
            job_id=job.id,
            outcome="claimed",
            summary={
                "worker_id": claim.worker_id,
                "ownership_token": claim.ownership_token,
                "lease_seconds": self._lease_seconds,
            },
        )
        return claim

    def _create_claim_and_lock(self, **kwargs) -> tuple[ApplicationJob, ApplicationJob]:
        job = self._create_job(**kwargs)
        claim = self._claim_job(job)
        try:
            self._acquire_operation_lock(job.operation, claim)
        except OperationInProgress as exc:
            self._complete_claim(
                claim,
                status=JOB_STATUS_FAILED,
                exit_code=None,
                result_summary="Job rejected because another high-risk operation is active.",
                stdout_summary=None,
                stderr_summary=None,
                failure_reason=str(exc),
                release_lock=False,
            )
            raise _operation_conflict(exc) from exc
        return job, claim

    def _complete_claim(
        self,
        claim: ApplicationJob,
        *,
        status: str,
        exit_code: int | None,
        result_summary: str | None,
        stdout_summary: str | None,
        stderr_summary: str | None,
        failure_reason: str | None,
        release_lock: bool = True,
    ) -> bool:
        completed = self.repository.complete(
            claim.id,
            worker_id=str(claim.worker_id),
            ownership_token=int(claim.ownership_token or 0),
            require_lock=release_lock,
            status=status,
            completed_at=self._clock(),
            exit_code=exit_code,
            result_summary=result_summary,
            stdout_summary=stdout_summary,
            stderr_summary=stderr_summary,
            failure_reason=failure_reason,
        )
        if completed:
            # PostgreSQL deletes the matching lock in the same transaction.
            # This call only releases the process-local compatibility guard.
            if release_lock:
                self._release_operation_lock(claim)
            return True
        _log_job_event(
            operation=claim.operation,
            job_id=claim.id,
            outcome="lease_lost",
            level="WARNING",
            summary={
                "worker_id": claim.worker_id,
                "ownership_token": claim.ownership_token,
                "attempted_status": status,
            },
        )
        return False

    def _start_heartbeat(
        self,
        claim: ApplicationJob,
        operation: str,
        *,
        phase: str = "running",
        on_loss=None,
    ) -> tuple[threading.Event, threading.Event, threading.Thread]:
        stop = threading.Event()
        lost = threading.Event()

        def _heartbeat() -> None:
            while not stop.wait(self._heartbeat_interval_seconds):
                try:
                    ok = self.repository.heartbeat(
                        job_id=claim.id,
                        worker_id=str(claim.worker_id),
                        ownership_token=int(claim.ownership_token or 0),
                        lease_seconds=self._lease_seconds,
                        progress={"operation": operation, "phase": phase},
                    )
                except Exception as exc:
                    ok = False
                    log_utils.log_event(
                        event="application_job_heartbeat",
                        message="application job heartbeat failed",
                        tag="JOB",
                        level="ERROR",
                        operation=operation,
                        job_id=claim.id,
                        worker_id=claim.worker_id,
                        ownership_token=claim.ownership_token,
                        error_type=type(exc).__name__,
                    )
                if ok:
                    continue
                lost.set()
                _log_job_event(
                    operation=operation,
                    job_id=claim.id,
                    outcome="lease_lost",
                    level="WARNING",
                    summary={
                        "worker_id": claim.worker_id,
                        "ownership_token": claim.ownership_token,
                    },
                )
                if callable(on_loss):
                    on_loss()
                break

        thread = threading.Thread(
            target=_heartbeat,
            name=f"{operation}-heartbeat-{claim.id}",
            daemon=True,
        )
        thread.start()
        return stop, lost, thread

    @staticmethod
    def _stop_heartbeat(stop: threading.Event, thread: threading.Thread) -> None:
        stop.set()
        thread.join(timeout=1.0)

    def _record_completion(
        self,
        *,
        operation: str,
        job_id: str,
        status: str,
        duration_seconds: float,
        exit_code: int | None = None,
        failure_reason: str | None = None,
    ) -> None:
        observability.record_job_completed(
            operation=operation,
            outcome=status,
            duration_seconds=duration_seconds,
        )
        context = {"duration_ms": round(duration_seconds * 1000, 2)}
        if exit_code is not None:
            context["return_code"] = exit_code
        alerts.record_operation_outcome(
            operation=operation,
            outcome=status,
            job_id=job_id,
            context=context,
        )
        _log_job_event(
            operation=operation,
            job_id=job_id,
            outcome=status,
            level="INFO" if status == JOB_STATUS_SUCCEEDED else "ERROR",
            summary={
                **context,
                "failure_reason": _safe_output_summary(failure_reason, limit=2000),
            },
        )

    def run_callback(
        self,
        *,
        job_id: str,
        operation: str,
        callback,
        requester: AuthUser | None,
        request_id: str,
        correlation_id: str,
        request_summary: dict[str, Any],
        timeout_seconds: float | None,
        auth_scheme: str | None = None,
        result_summary_builder=None,
        result_output_builder=None,
    ):
        job, claim = self._create_claim_and_lock(
            job_id=job_id,
            operation=operation,
            requester=requester,
            auth_scheme=auth_scheme,
            request_id=request_id,
            correlation_id=correlation_id,
            request_summary=request_summary,
        )
        parent_token = bind_log_context(job_id=job_id, component="job")
        worker_context = contextvars.copy_context()
        reset_log_context(parent_token)
        future = self._executor.submit(
            worker_context.run,
            self._run_callback_job,
            claim,
            operation,
            callback,
            result_summary_builder,
            result_output_builder,
        )
        if timeout_seconds is None or timeout_seconds <= 0:
            return future.result()
        try:
            return future.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError as exc:
            _log_job_event(
                operation=operation,
                job_id=job_id,
                outcome=JOB_STATUS_TIMEOUT,
                level="ERROR",
                summary={"timeout_seconds": timeout_seconds, "status": "still_running"},
            )
            raise HTTPException(
                status_code=504,
                detail={
                    "code": "command_timeout",
                    "message": f"{operation} exceeded {timeout_seconds:g}s timeout",
                    "operation": operation,
                    "timeout_seconds": timeout_seconds,
                    "job_id": job.id,
                },
            ) from exc

    def enqueue_callback(
        self,
        *,
        job_id: str,
        operation: str,
        callback,
        requester: AuthUser | None,
        request_id: str,
        correlation_id: str,
        request_summary: dict[str, Any],
        timeout_seconds: float | None,
        auth_scheme: str | None = None,
        result_summary_builder=None,
        result_output_builder=None,
    ) -> ApplicationJob:
        job, claim = self._create_claim_and_lock(
            job_id=job_id,
            operation=operation,
            requester=requester,
            auth_scheme=auth_scheme,
            request_id=request_id,
            correlation_id=correlation_id,
            request_summary=request_summary,
        )
        parent_token = bind_log_context(job_id=job_id, component="job")
        worker_context = contextvars.copy_context()
        reset_log_context(parent_token)
        self._executor.submit(
            worker_context.run,
            self._run_callback_job,
            claim,
            operation,
            callback,
            result_summary_builder,
            result_output_builder,
        )
        return job

    def _run_callback_job(
        self,
        claim: ApplicationJob,
        operation: str,
        callback,
        result_summary_builder=None,
        result_output_builder=None,
    ) -> Any:
        started = time.perf_counter()
        heartbeat_stop, _heartbeat_lost, heartbeat_thread = self._start_heartbeat(claim, operation)
        _log_job_event(
            operation=operation,
            job_id=claim.id,
            outcome=JOB_STATUS_RUNNING,
            summary={"worker_id": claim.worker_id, "ownership_token": claim.ownership_token},
        )
        status = JOB_STATUS_FAILED
        failure_reason: str | None = None
        result_summary = f"{operation} failed."
        stdout_summary: str | None = None
        result: Any = None
        callback_error: Exception | None = None
        try:
            result = callback()
            status = JOB_STATUS_FAILED if getattr(result, "success", True) is False else JOB_STATUS_SUCCEEDED
            if callable(result_summary_builder):
                result_summary = str(result_summary_builder(result))
            else:
                result_summary = _result_summary(operation, result, status=status)
            if callable(result_output_builder):
                stdout_summary = _safe_output_summary(str(result_output_builder(result)))
        except Exception as exc:
            callback_error = exc
            failure_reason = str(exc)
            result_summary = f"{operation} failed: {failure_reason}"
        finally:
            self._stop_heartbeat(heartbeat_stop, heartbeat_thread)

        duration_seconds = time.perf_counter() - started
        persisted = self._complete_claim(
            claim,
            status=status,
            exit_code=None,
            result_summary=result_summary,
            stdout_summary=stdout_summary,
            stderr_summary=None,
            failure_reason=failure_reason,
        )
        if not persisted:
            raise JobOwnershipLost(
                f"Job {claim.id} lost ownership token {claim.ownership_token} before completion"
            ) from callback_error
        self._record_completion(
            operation=operation,
            job_id=claim.id,
            status=status,
            duration_seconds=duration_seconds,
            failure_reason=failure_reason,
        )
        if callback_error is not None:
            raise callback_error
        return result

    def enqueue_subprocess(
        self,
        *,
        job_id: str,
        operation: str,
        command: list[str],
        requester: AuthUser | None,
        request_id: str,
        correlation_id: str,
        request_summary: dict[str, Any],
        timeout_seconds: float | None,
        auth_scheme: str | None = None,
    ) -> ApplicationJob:
        job, claim = self._create_claim_and_lock(
            job_id=job_id,
            operation=operation,
            requester=requester,
            auth_scheme=auth_scheme,
            request_id=request_id,
            correlation_id=correlation_id,
            request_summary=request_summary,
        )
        parent_token = bind_log_context(job_id=job_id, component="job")
        worker_context = contextvars.copy_context()
        reset_log_context(parent_token)
        threading.Thread(
            target=lambda: worker_context.run(
                self._run_subprocess_job,
                claim,
                operation,
                command,
                timeout_seconds,
            ),
            name=f"{operation}-job-{job_id}",
            daemon=True,
        ).start()
        return job

    def dispatch_external(
        self,
        *,
        job_id: str,
        operation: str,
        dispatch_command: list[str],
        requester: AuthUser | None,
        request_id: str,
        correlation_id: str,
        request_summary: dict[str, Any],
        auth_scheme: str | None = None,
        dispatch_timeout_seconds: float = 30.0,
    ) -> ApplicationJob:
        """Reserve a job, then ask an independent worker manager to take it over."""

        job, claim = self._create_claim_and_lock(
            job_id=job_id,
            operation=operation,
            requester=requester,
            auth_scheme=auth_scheme,
            request_id=request_id,
            correlation_id=correlation_id,
            request_summary=request_summary,
        )
        owns_dispatch = self.repository.heartbeat(
            job_id=claim.id,
            worker_id=str(claim.worker_id),
            ownership_token=int(claim.ownership_token or 0),
            lease_seconds=self._lease_seconds,
            progress={"operation": operation, "phase": "dispatching"},
        )
        if not owns_dispatch:
            raise JobOwnershipLost(f"Job {job_id} lost ownership before worker dispatch")
        heartbeat_stop, _heartbeat_lost, heartbeat_thread = self._start_heartbeat(
            claim,
            operation,
            phase="dispatching",
        )
        try:
            dispatched = subprocess.run(
                dispatch_command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(1.0, float(dispatch_timeout_seconds)),
                check=False,
            )
        except Exception as exc:
            self._complete_claim(
                claim,
                status=JOB_STATUS_FAILED,
                exit_code=None,
                result_summary=f"{operation} worker dispatch failed.",
                stdout_summary=None,
                stderr_summary=None,
                failure_reason=str(exc),
            )
            raise
        finally:
            self._stop_heartbeat(heartbeat_stop, heartbeat_thread)
        if dispatched.returncode != 0:
            stderr_summary = _safe_output_summary(dispatched.stderr)
            failure_reason = f"Worker dispatch exited with code {dispatched.returncode}."
            self._complete_claim(
                claim,
                status=JOB_STATUS_FAILED,
                exit_code=dispatched.returncode,
                result_summary=f"{operation} worker dispatch failed.",
                stdout_summary=_safe_output_summary(dispatched.stdout),
                stderr_summary=stderr_summary,
                failure_reason=failure_reason,
            )
            raise RuntimeError(failure_reason)
        _log_job_event(
            operation=operation,
            job_id=job_id,
            outcome="dispatched",
            summary={"worker_id": claim.worker_id, "ownership_token": claim.ownership_token},
        )
        return job

    def run_handed_off_subprocess(
        self,
        *,
        job_id: str,
        command: list[str],
        timeout_seconds: float | None,
        environment: Mapping[str, str] | None = None,
    ) -> bool:
        """Take over a dispatch claim and execute it in this independent worker."""

        current = self.repository.get(job_id)
        if (
            current is None
            or current.status != JOB_STATUS_RUNNING
            or current.worker_id is None
            or current.ownership_token is None
        ):
            return False
        claim = self.repository.handoff_claim(
            job_id,
            from_worker_id=current.worker_id,
            from_ownership_token=current.ownership_token,
            to_worker_id=self._worker_id,
            lease_seconds=self._lease_seconds,
        )
        if claim is None:
            _log_job_event(
                operation=current.operation,
                job_id=job_id,
                outcome="handoff_lost",
                level="WARNING",
                summary={"from_ownership_token": current.ownership_token},
            )
            return False
        _log_job_event(
            operation=claim.operation,
            job_id=job_id,
            outcome="claimed",
            summary={
                "worker_id": claim.worker_id,
                "ownership_token": claim.ownership_token,
                "handoff_from_token": current.ownership_token,
            },
        )
        return self._run_subprocess_job(
            claim,
            claim.operation,
            command,
            timeout_seconds,
            environment=environment,
        )

    def _terminate_active_process(self, job_id: str) -> None:
        with self._active_processes_lock:
            process = self._active_processes.get(job_id)
        if process is None:
            return
        terminate = getattr(process, "terminate", None)
        if callable(terminate):
            try:
                terminate()
            except Exception:
                pass

    def _run_subprocess_job(
        self,
        claim: ApplicationJob,
        operation: str,
        command: list[str],
        timeout_seconds: float | None,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> bool:
        started = time.perf_counter()
        heartbeat_stop, _heartbeat_lost, heartbeat_thread = self._start_heartbeat(
            claim,
            operation,
            on_loss=lambda: self._terminate_active_process(claim.id),
        )
        _log_job_event(
            operation=operation,
            job_id=claim.id,
            outcome=JOB_STATUS_RUNNING,
            summary={
                "command": command[:1],
                "worker_id": claim.worker_id,
                "ownership_token": claim.ownership_token,
            },
        )
        exit_code: int | None = None
        stdout_summary: str | None = None
        stderr_summary: str | None = None
        status = JOB_STATUS_FAILED
        failure_reason: str | None = None
        result_summary = f"{operation} failed."
        process: subprocess.Popen | None = None

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={**os.environ, **dict(environment or {})},
            )
            with self._active_processes_lock:
                self._active_processes[claim.id] = process
            try:
                stdout, stderr = process.communicate(
                    timeout=timeout_seconds if timeout_seconds and timeout_seconds > 0 else None
                )
                exit_code = process.returncode
                stdout_summary = _safe_output_summary(stdout)
                stderr_summary = _safe_output_summary(stderr)
                status = JOB_STATUS_SUCCEEDED if exit_code == 0 else JOB_STATUS_FAILED
                if exit_code == 0:
                    result_summary = f"{operation} completed successfully."
                else:
                    failure_reason = f"Process exited with code {exit_code}."
                    result_summary = f"{operation} failed with exit code {exit_code}."
            except subprocess.TimeoutExpired:
                status = JOB_STATUS_TIMEOUT
                failure_reason = f"Process exceeded {timeout_seconds:g}s timeout."
                process.kill()
                stdout, stderr = process.communicate()
                exit_code = process.returncode
                stdout_summary = _safe_output_summary(stdout)
                stderr_summary = _safe_output_summary(stderr)
                result_summary = f"{operation} timed out after {timeout_seconds:g}s."
        except Exception as exc:
            status = JOB_STATUS_FAILED
            failure_reason = str(exc)
            result_summary = f"{operation} failed before process completion."
        finally:
            with self._active_processes_lock:
                self._active_processes.pop(claim.id, None)
            self._stop_heartbeat(heartbeat_stop, heartbeat_thread)

        duration_seconds = time.perf_counter() - started
        persisted = self._complete_claim(
            claim,
            status=status,
            exit_code=exit_code,
            result_summary=result_summary,
            stdout_summary=stdout_summary,
            stderr_summary=stderr_summary,
            failure_reason=failure_reason,
        )
        if persisted:
            self._record_completion(
                operation=operation,
                job_id=claim.id,
                status=status,
                duration_seconds=duration_seconds,
                exit_code=exit_code,
                failure_reason=failure_reason,
            )
        return persisted

    def get_job(self, job_id: str) -> ApplicationJob | None:
        return self.repository.get(job_id)

    def list_recent_jobs(self, *, limit: int = 25) -> list[ApplicationJob]:
        return self.repository.list_recent(limit=limit)

    def list_current_jobs(self, *, limit: int = 10) -> list[ApplicationJob]:
        loader = getattr(self.repository, "list_current", None)
        if callable(loader):
            return loader(limit=limit)
        return [job for job in self.repository.list_recent(limit=limit) if not job.is_terminal]

    def record_command_event(
        self,
        *,
        request_id: str,
        correlation_id: str,
        job_id: str | None,
        requester: AuthUser | None,
        auth_scheme: str | None,
        command: str,
        outcome: str,
        summary: Mapping[str, Any] | None,
        client_identity: str | None,
    ) -> CommandHistoryEntry | None:
        recorder = getattr(self.repository, "record_command_event", None)
        if not callable(recorder):
            return None
        return recorder(
            request_id=request_id,
            correlation_id=correlation_id,
            job_id=job_id,
            requester_user_id=requester.id if requester is not None else None,
            requester_username=requester.username if requester is not None else None,
            auth_scheme=auth_scheme,
            command=command,
            outcome=outcome,
            safe_summary=safe_summary(summary),
            client_identity=client_identity,
        )

    def list_command_history(
        self,
        *,
        limit: int = 25,
        query: str | None = None,
        command: str | None = None,
        outcome: str | None = None,
    ) -> list[CommandHistoryEntry]:
        loader = getattr(self.repository, "list_command_history", None)
        if not callable(loader):
            return []
        return loader(limit=limit, query=query, command=command, outcome=outcome)


def _result_summary(operation: str, result: Any, *, status: str) -> str:
    summary_line = getattr(result, "summary_line", None)
    if callable(summary_line):
        request_days = getattr(result, "days", None)
        try:
            return str(summary_line(days=request_days)) if request_days is not None else str(summary_line(days=0))
        except TypeError:
            try:
                return str(summary_line())
            except TypeError:
                pass
    if status == JOB_STATUS_SUCCEEDED:
        return f"{operation} completed successfully."
    return f"{operation} completed with errors."
