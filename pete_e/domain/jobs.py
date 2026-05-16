from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


JOB_STATUS_QUEUED = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_SUCCEEDED = "succeeded"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_TIMEOUT = "timeout"
JOB_STATUS_ABANDONED = "abandoned"
JOB_STATUS_CANCELLED = "cancelled"

TERMINAL_JOB_STATUSES = frozenset(
    {
        JOB_STATUS_SUCCEEDED,
        JOB_STATUS_FAILED,
        JOB_STATUS_TIMEOUT,
        JOB_STATUS_ABANDONED,
        JOB_STATUS_CANCELLED,
    }
)


@dataclass(frozen=True)
class ApplicationJob:
    id: str
    operation: str
    requester_user_id: int | None
    requester_username: str | None
    status: str
    request_id: str
    correlation_id: str
    request_summary: dict[str, Any]
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime | None = None
    exit_code: int | None = None
    result_summary: str | None = None
    stdout_summary: str | None = None
    stderr_summary: str | None = None
    failure_reason: str | None = None
    auth_scheme: str | None = None
    worker_id: str | None = None
    attempt_number: int = 1
    lease_expires_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    ownership_token: int | None = None
    abandon_reason: str | None = None
    progress_summary: dict[str, Any] | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_JOB_STATUSES

    def to_status_payload(self, *, include_output: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "operation": self.operation,
            "requester": {
                "user_id": self.requester_user_id,
                "username": self.requester_username,
            },
            "auth_scheme": self.auth_scheme,
            "status": self.status,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "exit_code": self.exit_code,
            "result_summary": self.result_summary,
            "failure_reason": self.failure_reason,
            "worker_id": self.worker_id,
            "attempt_number": self.attempt_number,
            "lease_expires_at": self.lease_expires_at.isoformat() if self.lease_expires_at else None,
            "last_heartbeat_at": self.last_heartbeat_at.isoformat() if self.last_heartbeat_at else None,
            "ownership_token": self.ownership_token,
            "abandon_reason": self.abandon_reason,
            "progress_summary": dict(self.progress_summary or {}),
            "request_summary": dict(self.request_summary or {}),
        }
        if include_output:
            payload["stdout_summary"] = self.stdout_summary
            payload["stderr_summary"] = self.stderr_summary
        return payload


@dataclass(frozen=True)
class ApplicationOperationLock:
    lock_name: str
    operation: str
    job_id: str | None
    acquired_at: datetime | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True)
class CommandHistoryEntry:
    id: int | None
    request_id: str
    correlation_id: str
    job_id: str | None
    requester_user_id: int | None
    requester_username: str | None
    auth_scheme: str | None
    command: str
    outcome: str
    safe_summary: dict[str, Any]
    client_identity: str | None = None
    created_at: datetime | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "job_id": self.job_id,
            "requester": {
                "user_id": self.requester_user_id,
                "username": self.requester_username,
            },
            "auth_scheme": self.auth_scheme,
            "command": self.command,
            "outcome": self.outcome,
            "safe_summary": dict(self.safe_summary or {}),
            "client_identity": self.client_identity,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
