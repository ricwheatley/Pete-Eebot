from __future__ import annotations

import contextvars
import concurrent.futures
from datetime import datetime, timezone
import os
import re
import subprocess
import threading
import time
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

    def mark_running(self, job_id: str, *, started_at: datetime) -> None: ...

    def complete(
        self,
        job_id: str,
        *,
        status: str,
        completed_at: datetime,
        exit_code: int | None,
        result_summary: str | None,
        stdout_summary: str | None,
        stderr_summary: str | None,
        failure_reason: str | None,
    ) -> None: ...

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
        lease_seconds: float,
    ) -> object | None: ...

    def release_high_risk_operation_lock(self, *, job_id: str) -> None: ...

    def get_active_high_risk_operation_lock(self) -> object | None: ...


_SECRET_PATTERN = re.compile(r"(?i)(token|secret|password|api[_-]?key)=([^\s]+)")
_SECRET_KEY_PATTERN = re.compile(r"(?i)(token|secret|password|api[_-]?key|authorization|cookie)")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
    def __init__(self, repository: ApplicationJobRepository) -> None:
        self.repository = repository
        self._worker_id = "worker-local"
        self._lease_seconds = 300.0
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="application-job",
        )
        self.recover_stale_operations()

    def _lock_lease_seconds(self, timeout_seconds: float | None) -> float:
        configured_default = 14400.0
        if timeout_seconds is None or timeout_seconds <= 0:
            return configured_default
        return max(configured_default, float(timeout_seconds) * 2)

    def _active_operation_from_repository(self) -> str | None:
        active_loader = getattr(self.repository, "get_active_high_risk_operation_lock", None)
        if not callable(active_loader):
            return high_risk_operation_guard.active_operation
        active_lock = active_loader()
        return str(getattr(active_lock, "operation", "") or "") or None

    def _acquire_operation_lock(self, operation: str, job_id: str, timeout_seconds: float | None) -> None:
        acquire = getattr(self.repository, "acquire_high_risk_operation_lock", None)
        if not callable(acquire):
            high_risk_operation_guard.acquire(operation)
            return
        lock = acquire(
            operation=operation,
            job_id=job_id,
            lease_seconds=self._lock_lease_seconds(timeout_seconds),
        )
        if lock is None:
            raise OperationInProgress(
                requested_operation=operation,
                active_operation=self._active_operation_from_repository(),
            )

    def _release_operation_lock(self, job_id: str) -> None:
        release = getattr(self.repository, "release_high_risk_operation_lock", None)
        if callable(release):
            release(job_id=job_id)
            return
        high_risk_operation_guard.release()

    def recover_stale_operations(self) -> int:
        recover = getattr(self.repository, "recover_stale_operations", None)
        if not callable(recover):
            return 0
        return int(recover(stale_before=_utcnow()))

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
    ):
        job = self._create_job(
            job_id=job_id,
            operation=operation,
            requester=requester,
            auth_scheme=auth_scheme,
            request_id=request_id,
            correlation_id=correlation_id,
            request_summary=request_summary,
        )

        try:
            self._acquire_operation_lock(operation, job_id, timeout_seconds)
        except OperationInProgress as exc:
            self.repository.complete(
                job_id,
                status=JOB_STATUS_FAILED,
                completed_at=_utcnow(),
                exit_code=None,
                result_summary="Job rejected because another high-risk operation is active.",
                stdout_summary=None,
                stderr_summary=None,
                failure_reason=str(exc),
            )
            raise _operation_conflict(exc) from exc

        parent_token = bind_log_context(job_id=job_id, component="job")
        worker_context = contextvars.copy_context()
        reset_log_context(parent_token)
        future = self._executor.submit(
            worker_context.run,
            self._run_callback_job,
            job_id,
            operation,
            callback,
            result_summary_builder,
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

    def _run_callback_job(self, job_id: str, operation: str, callback, result_summary_builder=None) -> Any:
        started = time.perf_counter()
        self.repository.mark_running(job_id, started_at=_utcnow())
        _log_job_event(operation=operation, job_id=job_id, outcome=JOB_STATUS_RUNNING)
        status = JOB_STATUS_FAILED
        failure_reason: str | None = None
        result_summary = f"{operation} failed."
        result: Any = None
        try:
            result = callback()
            status = JOB_STATUS_FAILED if getattr(result, "success", True) is False else JOB_STATUS_SUCCEEDED
            if callable(result_summary_builder):
                result_summary = str(result_summary_builder(result))
            else:
                result_summary = _result_summary(operation, result, status=status)
            return result
        except Exception as exc:
            failure_reason = str(exc)
            result_summary = f"{operation} failed: {failure_reason}"
            raise
        finally:
            duration_seconds = time.perf_counter() - started
            self.repository.complete(
                job_id,
                status=status,
                completed_at=_utcnow(),
                exit_code=None,
                result_summary=result_summary,
                stdout_summary=None,
                stderr_summary=None,
                failure_reason=failure_reason,
            )
            observability.record_job_completed(
                operation=operation,
                outcome=status,
                duration_seconds=duration_seconds,
            )
            alerts.record_operation_outcome(
                operation=operation,
                outcome=status,
                job_id=job_id,
                context={"duration_ms": round(duration_seconds * 1000, 2)},
            )
            _log_job_event(
                operation=operation,
                job_id=job_id,
                outcome=status,
                level="INFO" if status == JOB_STATUS_SUCCEEDED else "ERROR",
                summary={"duration_ms": round(duration_seconds * 1000, 2), "failure_reason": failure_reason},
            )
            self._release_operation_lock(job_id)

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
        job = self._create_job(
            job_id=job_id,
            operation=operation,
            requester=requester,
            auth_scheme=auth_scheme,
            request_id=request_id,
            correlation_id=correlation_id,
            request_summary=request_summary,
        )

        try:
            self._acquire_operation_lock(operation, job_id, timeout_seconds)
        except OperationInProgress as exc:
            self.repository.complete(
                job_id,
                status=JOB_STATUS_FAILED,
                completed_at=_utcnow(),
                exit_code=None,
                result_summary="Job rejected because another high-risk operation is active.",
                stdout_summary=None,
                stderr_summary=None,
                failure_reason=str(exc),
            )
            raise _operation_conflict(exc) from exc

        parent_token = bind_log_context(job_id=job_id, component="job")
        worker_context = contextvars.copy_context()
        reset_log_context(parent_token)
        threading.Thread(
            target=lambda: worker_context.run(
                self._run_subprocess_job,
                job_id,
                operation,
                command,
                timeout_seconds,
            ),
            name=f"{operation}-job-{job_id}",
            daemon=True,
        ).start()
        return job

    def _run_subprocess_job(
        self,
        job_id: str,
        operation: str,
        command: list[str],
        timeout_seconds: float | None,
    ) -> None:
        started = time.perf_counter()
        self.repository.mark_running(job_id, started_at=_utcnow())
        heartbeat_stop = threading.Event()

        def _heartbeat() -> None:
            sender = getattr(self.repository, "heartbeat", None)
            while not heartbeat_stop.wait(self._lease_seconds / 3):
                if callable(sender):
                    ok = sender(
                        job_id=job_id,
                        worker_id=self._worker_id,
                        lease_seconds=self._lease_seconds,
                        progress={"operation": operation, "phase": "running"},
                    )
                    if not ok:
                        break

        heartbeat_thread = threading.Thread(target=_heartbeat, name=f"{operation}-heartbeat-{job_id}", daemon=True)
        heartbeat_thread.start()
        _log_job_event(operation=operation, job_id=job_id, outcome=JOB_STATUS_RUNNING, summary={"command": command[:1]})
        exit_code: int | None = None
        stdout_summary: str | None = None
        stderr_summary: str | None = None
        status = JOB_STATUS_FAILED
        failure_reason: str | None = None
        result_summary = f"{operation} failed."

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            try:
                stdout, stderr = process.communicate(timeout=timeout_seconds if timeout_seconds and timeout_seconds > 0 else None)
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
            heartbeat_stop.set()
            duration_seconds = time.perf_counter() - started
            self.repository.complete(
                job_id,
                status=status,
                completed_at=_utcnow(),
                exit_code=exit_code,
                result_summary=result_summary,
                stdout_summary=stdout_summary,
                stderr_summary=stderr_summary,
                failure_reason=failure_reason,
            )
            observability.record_job_completed(
                operation=operation,
                outcome=status,
                duration_seconds=duration_seconds,
            )
            alerts.record_operation_outcome(
                operation=operation,
                outcome=status,
                job_id=job_id,
                context={"return_code": exit_code, "duration_ms": round(duration_seconds * 1000, 2)},
            )
            _log_job_event(
                operation=operation,
                job_id=job_id,
                outcome=status,
                level="INFO" if status == JOB_STATUS_SUCCEEDED else "ERROR",
                summary={
                    "return_code": exit_code,
                    "duration_ms": round(duration_seconds * 1000, 2),
                    "failure_reason": failure_reason,
                },
            )
            self._release_operation_lock(job_id)

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
