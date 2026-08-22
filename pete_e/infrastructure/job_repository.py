"""PostgreSQL persistence for application command jobs and operation locks."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Json
from psycopg_pool import ConnectionPool

from pete_e.domain.jobs import (
    ApplicationJob,
    ApplicationOperationLock,
    CommandHistoryEntry,
    JOB_STATUS_ABANDONED,
    JOB_STATUS_QUEUED,
)
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
            worker_id=row.get("worker_id"),
            attempt_number=int(row.get("attempt_number") or 1),
            lease_expires_at=row.get("lease_expires_at"),
            last_heartbeat_at=row.get("last_heartbeat_at"),
            ownership_token=int(row["ownership_token"]) if row.get("ownership_token") is not None else None,
            abandon_reason=row.get("abandon_reason"),
            progress_summary=dict(row.get("progress_summary") or {}),
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
            worker_id=row.get("worker_id"),
            ownership_token=(
                int(row["ownership_token"])
                if row.get("ownership_token") is not None
                else None
            ),
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

    def claim(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_seconds: float,
    ) -> ApplicationJob | None:
        """Atomically claim a queued job or take over an expired running claim."""

        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    UPDATE application_jobs
                    SET status = 'running',
                        started_at = COALESCE(started_at, now()),
                        worker_id = %s,
                        attempt_number = CASE
                            WHEN status = 'queued' THEN attempt_number
                            ELSE attempt_number + 1
                        END,
                        last_heartbeat_at = now(),
                        lease_expires_at = now() + (%s || ' seconds')::interval,
                        ownership_token = ownership_token + 1,
                        abandon_reason = NULL,
                        updated_at = now()
                    WHERE id = %s
                      AND (
                          status = 'queued'
                          OR (
                              status = 'running'
                              AND lease_expires_at IS NOT NULL
                              AND lease_expires_at < now()
                          )
                      )
                    RETURNING *
                    """,
                    (worker_id, max(0.001, float(lease_seconds)), job_id),
                )
                row = cur.fetchone()
        return self._job_from_row(row) if row else None

    def handoff_claim(
        self,
        job_id: str,
        *,
        from_worker_id: str,
        from_ownership_token: int,
        to_worker_id: str,
        lease_seconds: float,
    ) -> ApplicationJob | None:
        """Transfer an active claim and its operation lock to another process."""

        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    UPDATE application_jobs
                    SET worker_id = %s,
                        ownership_token = ownership_token + 1,
                        last_heartbeat_at = now(),
                        lease_expires_at = now() + (%s || ' seconds')::interval,
                        progress_summary = COALESCE(progress_summary, '{}'::jsonb)
                            || '{"phase":"running"}'::jsonb,
                        updated_at = now()
                    WHERE id = %s
                      AND status = 'running'
                      AND worker_id = %s
                      AND ownership_token = %s
                      AND lease_expires_at >= now()
                      AND progress_summary ->> 'phase' = 'dispatching'
                    RETURNING *
                    """,
                    (
                        to_worker_id,
                        max(0.001, float(lease_seconds)),
                        job_id,
                        from_worker_id,
                        int(from_ownership_token),
                    ),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                new_token = int(row["ownership_token"])
                cur.execute(
                    """
                    UPDATE application_operation_locks
                    SET worker_id = %s,
                        ownership_token = %s,
                        expires_at = now() + (%s || ' seconds')::interval,
                        updated_at = now()
                    WHERE lock_name = 'high_risk_operation'
                      AND job_id = %s
                      AND worker_id = %s
                      AND ownership_token = %s
                    """,
                    (
                        to_worker_id,
                        new_token,
                        max(0.001, float(lease_seconds)),
                        job_id,
                        from_worker_id,
                        int(from_ownership_token),
                    ),
                )
                if cur.rowcount != 1:
                    conn.rollback()
                    return None
        return self._job_from_row(row)

    def heartbeat(
        self,
        *,
        job_id: str,
        worker_id: str,
        ownership_token: int,
        lease_seconds: float,
        progress: dict[str, Any] | None = None,
    ) -> bool:
        """Renew the job and matching operation lock, or renew neither."""

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE application_jobs
                    SET last_heartbeat_at = now(),
                        lease_expires_at = now() + (%s || ' seconds')::interval,
                        progress_summary = COALESCE(%s::jsonb, progress_summary),
                        updated_at = now()
                    WHERE id = %s
                      AND status = 'running'
                      AND worker_id = %s
                      AND ownership_token = %s
                      AND lease_expires_at >= now()
                    """,
                    (
                        max(0.001, float(lease_seconds)),
                        Json(progress) if progress is not None else None,
                        job_id,
                        worker_id,
                        int(ownership_token),
                    ),
                )
                if cur.rowcount != 1:
                    return False
                cur.execute(
                    """
                    UPDATE application_operation_locks
                    SET expires_at = now() + (%s || ' seconds')::interval,
                        updated_at = now()
                    WHERE lock_name = 'high_risk_operation'
                      AND job_id = %s
                      AND worker_id = %s
                      AND ownership_token = %s
                    """,
                    (
                        max(0.001, float(lease_seconds)),
                        job_id,
                        worker_id,
                        int(ownership_token),
                    ),
                )
                if cur.rowcount != 1:
                    conn.rollback()
                    return False
                return True

    def recover_stale_operations(
        self,
        *,
        stale_before: datetime,
        queued_before: datetime | None = None,
    ) -> int:
        """Abandon expired work and prune only locks whose exact owner is stale."""

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE application_jobs
                    SET status = %s,
                        completed_at = now(),
                        abandon_reason = 'lease_expired',
                        failure_reason = COALESCE(failure_reason, 'lease_expired'),
                        result_summary = COALESCE(result_summary, 'Operation abandoned after missed heartbeat.'),
                        updated_at = now()
                    WHERE (
                        status = 'running'
                        AND lease_expires_at IS NOT NULL
                        AND lease_expires_at < LEAST(%s, now())
                    ) OR (
                        status = 'queued'
                        AND created_at < LEAST(%s, now())
                    )
                    """,
                    (
                        JOB_STATUS_ABANDONED,
                        stale_before,
                        queued_before or stale_before,
                    ),
                )
                recovered = cur.rowcount
                cur.execute(
                    """
                    DELETE FROM application_operation_locks l
                    WHERE l.lock_name = 'high_risk_operation'
                      AND (
                          l.expires_at < now()
                          OR NOT EXISTS (
                              SELECT 1
                              FROM application_jobs j
                              WHERE j.id = l.job_id
                                AND j.status = 'running'
                                AND j.worker_id = l.worker_id
                                AND j.ownership_token = l.ownership_token
                                AND j.lease_expires_at >= now()
                          )
                      )
                    """
                )
                return recovered

    def complete(
        self,
        job_id: str,
        *,
        worker_id: str,
        ownership_token: int,
        require_lock: bool = True,
        status: str,
        completed_at: datetime,
        exit_code: int | None,
        result_summary: str | None,
        stdout_summary: str | None,
        stderr_summary: str | None,
        failure_reason: str | None,
    ) -> bool:
        """Persist a terminal result and delete its matching lock atomically."""

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
                      AND status = 'running'
                      AND worker_id = %s
                      AND ownership_token = %s
                      AND lease_expires_at >= now()
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
                        worker_id,
                        int(ownership_token),
                    ),
                )
                if cur.rowcount != 1:
                    return False
                cur.execute(
                    """
                    DELETE FROM application_operation_locks
                    WHERE lock_name = 'high_risk_operation'
                      AND job_id = %s
                      AND worker_id = %s
                      AND ownership_token = %s
                    """,
                    (job_id, worker_id, int(ownership_token)),
                )
                if require_lock and cur.rowcount != 1:
                    conn.rollback()
                    return False
                return True

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
        worker_id: str,
        ownership_token: int,
        lease_seconds: float,
    ) -> ApplicationOperationLock | None:
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    INSERT INTO application_operation_locks (
                        lock_name,
                        operation,
                        job_id,
                        worker_id,
                        ownership_token,
                        acquired_at,
                        expires_at
                    )
                    SELECT 'high_risk_operation', %s, j.id, %s, %s,
                           now(), now() + (%s || ' seconds')::interval
                    FROM application_jobs j
                    WHERE j.id = %s
                      AND j.status = 'running'
                      AND j.worker_id = %s
                      AND j.ownership_token = %s
                      AND j.lease_expires_at >= now()
                    ON CONFLICT (lock_name) DO UPDATE
                    SET operation = EXCLUDED.operation,
                        job_id = EXCLUDED.job_id,
                        worker_id = EXCLUDED.worker_id,
                        ownership_token = EXCLUDED.ownership_token,
                        acquired_at = EXCLUDED.acquired_at,
                        expires_at = EXCLUDED.expires_at,
                        updated_at = now()
                    WHERE application_operation_locks.expires_at < now()
                       OR NOT EXISTS (
                           SELECT 1
                           FROM application_jobs active_job
                           WHERE active_job.id = application_operation_locks.job_id
                             AND active_job.status = 'running'
                             AND active_job.worker_id = application_operation_locks.worker_id
                             AND active_job.ownership_token = application_operation_locks.ownership_token
                             AND active_job.lease_expires_at >= now()
                       )
                    RETURNING *
                    """,
                    (
                        operation,
                        worker_id,
                        int(ownership_token),
                        max(0.001, float(lease_seconds)),
                        job_id,
                        worker_id,
                        int(ownership_token),
                    ),
                )
                row = cur.fetchone()
        return self._lock_from_row(row) if row else None

    @staticmethod
    def _prune_orphaned_high_risk_lock(cur) -> None:
        cur.execute(
            """
            DELETE FROM application_operation_locks l
            WHERE l.lock_name = 'high_risk_operation'
              AND l.job_id IS NOT NULL
              AND EXISTS (
                  SELECT 1
                  FROM application_jobs j
                  WHERE j.id = l.job_id
                    AND (
                        j.status <> 'running'
                        OR j.worker_id IS DISTINCT FROM l.worker_id
                        OR j.ownership_token IS DISTINCT FROM l.ownership_token
                        OR j.lease_expires_at < now()
                    )
              )
            """
        )

    def release_high_risk_operation_lock(
        self,
        *,
        job_id: str,
        worker_id: str,
        ownership_token: int,
    ) -> bool:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM application_operation_locks
                    WHERE lock_name = 'high_risk_operation'
                      AND job_id = %s
                      AND worker_id = %s
                      AND ownership_token = %s
                    """,
                    (job_id, worker_id, int(ownership_token)),
                )
                return cur.rowcount == 1

    def get_active_high_risk_operation_lock(self) -> ApplicationOperationLock | None:
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                self._prune_orphaned_high_risk_lock(cur)
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
