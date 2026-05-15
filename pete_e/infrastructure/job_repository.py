"""PostgreSQL persistence for application command jobs and operation locks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Json
from psycopg_pool import ConnectionPool

from pete_e.domain.jobs import ApplicationJob, ApplicationOperationLock, CommandHistoryEntry, JOB_STATUS_QUEUED
from pete_e.infrastructure.postgres_dal import get_pool


class PostgresApplicationJobRepository:
    def __init__(self, pool: ConnectionPool | None = None) -> None:
        self.pool = pool or get_pool()

    @staticmethod
    def _job_from_row(row: dict[str, Any]) -> ApplicationJob:
        return ApplicationJob(
            id=str(row["id"]),
            operation=str(row["operation"]),
            requester_user_id=int(row["requester_user_id"]) if row.get("requester_user_id") is not None else None,
            requester_username=row.get("requester_username"),
            auth_scheme=row.get("auth_scheme"),
            status=str(row["status"]),
            request_id=str(row["request_id"]),
            correlation_id=str(row["correlation_id"]),
            request_summary=dict(row.get("request_summary") or {}),
            created_at=row.get("created_at"),
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
            updated_at=row.get("updated_at"),
            exit_code=int(row["exit_code"]) if row.get("exit_code") is not None else None,
            result_summary=row.get("result_summary"),
            stdout_summary=row.get("stdout_summary"),
            stderr_summary=row.get("stderr_summary"),
            failure_reason=row.get("failure_reason"),
        )

    @staticmethod
    def _history_from_row(row: dict[str, Any]) -> CommandHistoryEntry:
        return CommandHistoryEntry(
            id=int(row["id"]) if row.get("id") is not None else None,
            request_id=str(row["request_id"]),
            correlation_id=str(row["correlation_id"]),
            job_id=str(row["job_id"]) if row.get("job_id") is not None else None,
            requester_user_id=int(row["requester_user_id"]) if row.get("requester_user_id") is not None else None,
            requester_username=row.get("requester_username"),
            auth_scheme=row.get("auth_scheme"),
            command=str(row["command"]),
            outcome=str(row["outcome"]),
            safe_summary=dict(row.get("safe_summary") or {}),
            client_identity=row.get("client_identity"),
            created_at=row.get("created_at"),
        )

    @staticmethod
    def _lock_from_row(row: dict[str, Any]) -> ApplicationOperationLock:
        return ApplicationOperationLock(
            lock_name=str(row["lock_name"]),
            operation=str(row["operation"]),
            job_id=str(row["job_id"]) if row.get("job_id") is not None else None,
            acquired_at=row.get("acquired_at"),
            expires_at=row.get("expires_at"),
        )

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
    ) -> ApplicationJob:
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    INSERT INTO application_jobs (
                        id,
                        operation,
                        requester_user_id,
                        requester_username,
                        auth_scheme,
                        status,
                        request_id,
                        correlation_id,
                        request_summary
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        job_id,
                        operation,
                        requester_user_id,
                        requester_username,
                        auth_scheme,
                        JOB_STATUS_QUEUED,
                        request_id,
                        correlation_id,
                        Json(request_summary),
                    ),
                )
                row = cur.fetchone()
        return self._job_from_row(row)

    def mark_running(self, job_id: str, *, started_at: datetime) -> None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE application_jobs
                    SET status = 'running',
                        started_at = %s,
                        updated_at = now()
                    WHERE id = %s
                    """,
                    (started_at, job_id),
                )

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
    ) -> None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE application_jobs
                    SET status = %s,
                        completed_at = %s,
                        updated_at = now(),
                        exit_code = %s,
                        result_summary = %s,
                        stdout_summary = %s,
                        stderr_summary = %s,
                        failure_reason = %s
                    WHERE id = %s
                    """,
                    (
                        status,
                        completed_at,
                        exit_code,
                        result_summary,
                        stdout_summary,
                        stderr_summary,
                        failure_reason,
                        job_id,
                    ),
                )

    def get(self, job_id: str) -> ApplicationJob | None:
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM application_jobs
                    WHERE id = %s
                    LIMIT 1
                    """,
                    (job_id,),
                )
                row = cur.fetchone()
        return self._job_from_row(row) if row else None

    def list_recent(self, *, limit: int = 25) -> list[ApplicationJob]:
        bounded_limit = max(1, min(int(limit), 100))
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM application_jobs
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (bounded_limit,),
                )
                rows = cur.fetchall()
        return [self._job_from_row(row) for row in rows]

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
    ) -> CommandHistoryEntry:
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    INSERT INTO web_console_command_history (
                        request_id,
                        correlation_id,
                        job_id,
                        requester_user_id,
                        requester_username,
                        auth_scheme,
                        command,
                        outcome,
                        safe_summary,
                        client_identity
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        request_id,
                        correlation_id,
                        job_id,
                        requester_user_id,
                        requester_username,
                        auth_scheme,
                        command,
                        outcome,
                        Json(safe_summary),
                        client_identity,
                    ),
                )
                row = cur.fetchone()
        return self._history_from_row(row)

    def list_command_history(
        self,
        *,
        limit: int = 25,
        query: str | None = None,
        command: str | None = None,
        outcome: str | None = None,
    ) -> list[CommandHistoryEntry]:
        bounded_limit = max(1, min(int(limit), 100))
        filters = []
        params: list[Any] = []
        if command:
            filters.append("command = %s")
            params.append(command)
        if outcome:
            filters.append("outcome = %s")
            params.append(outcome)
        if query:
            like = f"%{query}%"
            filters.append(
                """
                (
                    request_id ILIKE %s
                    OR correlation_id ILIKE %s
                    OR COALESCE(job_id, '') ILIKE %s
                    OR COALESCE(requester_username, '') ILIKE %s
                    OR COALESCE(auth_scheme, '') ILIKE %s
                    OR command ILIKE %s
                    OR outcome ILIKE %s
                    OR safe_summary::text ILIKE %s
                )
                """
            )
            params.extend([like] * 8)
        where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.append(bounded_limit)
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT *
                    FROM web_console_command_history
                    {where_sql}
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                rows = cur.fetchall()
        return [self._history_from_row(row) for row in rows]

    def list_current(self, *, limit: int = 10) -> list[ApplicationJob]:
        bounded_limit = max(1, min(int(limit), 100))
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM application_jobs
                    WHERE status IN ('queued', 'running')
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (bounded_limit,),
                )
                rows = cur.fetchall()
        return [self._job_from_row(row) for row in rows]

    def acquire_high_risk_operation_lock(
        self,
        *,
        operation: str,
        job_id: str,
        lease_seconds: float,
    ) -> ApplicationOperationLock | None:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=max(60.0, float(lease_seconds)))
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    DELETE FROM application_operation_locks
                    WHERE lock_name = 'high_risk_operation'
                      AND expires_at IS NOT NULL
                      AND expires_at < now()
                    """
                )
                cur.execute(
                    """
                    INSERT INTO application_operation_locks (
                        lock_name,
                        operation,
                        job_id,
                        acquired_at,
                        expires_at
                    )
                    VALUES ('high_risk_operation', %s, %s, %s, %s)
                    ON CONFLICT (lock_name) DO NOTHING
                    RETURNING *
                    """,
                    (operation, job_id, now, expires_at),
                )
                row = cur.fetchone()
        return self._lock_from_row(row) if row else None

    def release_high_risk_operation_lock(self, *, job_id: str) -> None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM application_operation_locks
                    WHERE lock_name = 'high_risk_operation'
                      AND job_id = %s
                    """,
                    (job_id,),
                )

    def get_active_high_risk_operation_lock(self) -> ApplicationOperationLock | None:
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM application_operation_locks
                    WHERE lock_name = 'high_risk_operation'
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
        return self._lock_from_row(row) if row else None
