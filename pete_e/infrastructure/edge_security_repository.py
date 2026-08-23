"""PostgreSQL-backed rate-limit counters and GitHub delivery replay ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import math
from typing import Iterable

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from pete_e.infrastructure.postgres_dal import get_pool


@dataclass(frozen=True)
class RateLimitRule:
    scope: str
    subject: str
    max_requests: int
    window_seconds: float
    backoff_base_seconds: float = 0.0
    lockout_seconds: float = 0.0


@dataclass(frozen=True)
class RateLimitDecision:
    code: str
    retry_after_seconds: int


@dataclass(frozen=True)
class DeliveryClaim:
    accepted: bool
    delivery_id: str
    job_id: str
    status: str


def _subject_hash(scope: str, subject: str) -> str:
    material = f"{scope}\0{subject}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _advisory_lock_id(subject_hash: str) -> int:
    unsigned = int(subject_hash[:16], 16)
    return unsigned - (1 << 64) if unsigned >= (1 << 63) else unsigned


class PostgresEdgeSecurityRepository:
    """Coordinate edge controls across workers and process restarts."""

    def __init__(self, pool: ConnectionPool | None = None) -> None:
        self.pool = pool or get_pool()

    @staticmethod
    def _active_rules(rules: Iterable[RateLimitRule]) -> tuple[RateLimitRule, ...]:
        return tuple(
            rule
            for rule in rules
            if rule.max_requests > 0 and rule.window_seconds > 0
        )

    @staticmethod
    def _decision(row, rule: RateLimitRule, now: datetime) -> RateLimitDecision | None:
        locked_until = row.get("locked_until") if row else None
        if locked_until is not None and locked_until > now:
            return RateLimitDecision(
                "login_locked",
                max(1, math.ceil((locked_until - now).total_seconds())),
            )
        next_allowed_at = row.get("next_allowed_at") if row else None
        if next_allowed_at is not None and next_allowed_at > now:
            return RateLimitDecision(
                "login_backoff",
                max(1, math.ceil((next_allowed_at - now).total_seconds())),
            )
        if row is None:
            return None
        window_started_at = row["window_started_at"]
        window_end = window_started_at + timedelta(seconds=rule.window_seconds)
        if now < window_end and int(row["event_count"]) >= rule.max_requests:
            return RateLimitDecision(
                "rate_limited",
                max(1, math.ceil((window_end - now).total_seconds())),
            )
        return None

    @staticmethod
    def _fetch_row(cur, rule: RateLimitRule):
        cur.execute(
            """
            SELECT scope, subject_hash, window_started_at, event_count,
                   next_allowed_at, locked_until
            FROM edge_rate_limit_counters
            WHERE scope = %s AND subject_hash = %s
            """,
            (rule.scope, _subject_hash(rule.scope, rule.subject)),
        )
        return cur.fetchone()

    @staticmethod
    def _lock_rules(cur, rules: tuple[RateLimitRule, ...]) -> None:
        lock_ids = sorted(
            {
                _advisory_lock_id(_subject_hash(rule.scope, rule.subject))
                for rule in rules
            }
        )
        for lock_id in lock_ids:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (lock_id,))

    def check_rate_limits(self, rules: Iterable[RateLimitRule]) -> RateLimitDecision | None:
        active = self._active_rules(rules)
        if not active:
            return None
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                self._lock_rules(cur, active)
                cur.execute("SELECT clock_timestamp() AS now")
                now = cur.fetchone()["now"]
                for rule in active:
                    decision = self._decision(self._fetch_row(cur, rule), rule, now)
                    if decision is not None:
                        return decision
        return None

    def consume_rate_limits(self, rules: Iterable[RateLimitRule]) -> RateLimitDecision | None:
        active = self._active_rules(rules)
        if not active:
            return None
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                self._lock_rules(cur, active)
                cur.execute("SELECT clock_timestamp() AS now")
                now = cur.fetchone()["now"]
                rows = [(rule, self._fetch_row(cur, rule)) for rule in active]
                for rule, row in rows:
                    decision = self._decision(row, rule, now)
                    if decision is not None:
                        return decision
                for rule, row in rows:
                    expired = (
                        row is None
                        or now >= row["window_started_at"] + timedelta(seconds=rule.window_seconds)
                    )
                    window_started_at = now if expired else row["window_started_at"]
                    event_count = 1 if expired else int(row["event_count"]) + 1
                    cur.execute(
                        """
                        INSERT INTO edge_rate_limit_counters (
                            scope, subject_hash, window_started_at, event_count,
                            next_allowed_at, locked_until, updated_at
                        )
                        VALUES (%s, %s, %s, %s, NULL, NULL, %s)
                        ON CONFLICT (scope, subject_hash) DO UPDATE
                        SET window_started_at = EXCLUDED.window_started_at,
                            event_count = EXCLUDED.event_count,
                            next_allowed_at = NULL,
                            locked_until = NULL,
                            updated_at = EXCLUDED.updated_at
                        """,
                        (
                            rule.scope,
                            _subject_hash(rule.scope, rule.subject),
                            window_started_at,
                            event_count,
                            now,
                        ),
                    )
        return None

    def record_failures(self, rules: Iterable[RateLimitRule]) -> RateLimitDecision | None:
        active = self._active_rules(rules)
        if not active:
            return None
        result: RateLimitDecision | None = None
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                self._lock_rules(cur, active)
                cur.execute("SELECT clock_timestamp() AS now")
                now = cur.fetchone()["now"]
                for rule in active:
                    row = self._fetch_row(cur, rule)
                    expired = (
                        row is None
                        or now >= row["window_started_at"] + timedelta(seconds=rule.window_seconds)
                    )
                    window_started_at = now if expired else row["window_started_at"]
                    event_count = 1 if expired else int(row["event_count"]) + 1
                    locked_until = None
                    next_allowed_at = None
                    if event_count >= rule.max_requests and rule.lockout_seconds > 0:
                        locked_until = now + timedelta(seconds=rule.lockout_seconds)
                        next_allowed_at = locked_until
                        decision = RateLimitDecision(
                            "login_locked",
                            max(1, math.ceil(rule.lockout_seconds)),
                        )
                        if result is None or decision.retry_after_seconds > result.retry_after_seconds:
                            result = decision
                    elif rule.backoff_base_seconds > 0:
                        backoff = rule.backoff_base_seconds * (2 ** max(0, event_count - 1))
                        if rule.lockout_seconds > 0:
                            backoff = min(backoff, rule.lockout_seconds)
                        next_allowed_at = now + timedelta(seconds=backoff)
                    cur.execute(
                        """
                        INSERT INTO edge_rate_limit_counters (
                            scope, subject_hash, window_started_at, event_count,
                            next_allowed_at, locked_until, updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (scope, subject_hash) DO UPDATE
                        SET window_started_at = EXCLUDED.window_started_at,
                            event_count = EXCLUDED.event_count,
                            next_allowed_at = EXCLUDED.next_allowed_at,
                            locked_until = EXCLUDED.locked_until,
                            updated_at = EXCLUDED.updated_at
                        """,
                        (
                            rule.scope,
                            _subject_hash(rule.scope, rule.subject),
                            window_started_at,
                            event_count,
                            next_allowed_at,
                            locked_until,
                            now,
                        ),
                    )
        return result

    def clear_rate_limits(self, rules: Iterable[RateLimitRule]) -> None:
        active = self._active_rules(rules)
        if not active:
            return
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                self._lock_rules(cur, active)
                cur.executemany(
                    "DELETE FROM edge_rate_limit_counters WHERE scope = %s AND subject_hash = %s",
                    [
                        (rule.scope, _subject_hash(rule.scope, rule.subject))
                        for rule in active
                    ],
                )

    def claim_github_delivery(
        self,
        *,
        delivery_id: str,
        repository_id: int,
        event_name: str,
        ref_name: str,
        commit_sha: str,
        job_id: str,
    ) -> DeliveryClaim:
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    INSERT INTO github_webhook_deliveries (
                        delivery_id, repository_id, event_name, ref_name,
                        commit_sha, job_id, status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 'accepted')
                    ON CONFLICT DO NOTHING
                    RETURNING delivery_id, job_id, status
                    """,
                    (delivery_id, repository_id, event_name, ref_name, commit_sha, job_id),
                )
                row = cur.fetchone()
                if row is not None:
                    return DeliveryClaim(True, str(row["delivery_id"]), str(row["job_id"]), str(row["status"]))
                cur.execute(
                    """
                    SELECT delivery_id, job_id, status
                    FROM github_webhook_deliveries
                    WHERE delivery_id = %s
                       OR (
                           repository_id = %s
                           AND event_name = %s
                           AND ref_name = %s
                           AND commit_sha = %s
                       )
                    ORDER BY (delivery_id = %s) DESC
                    LIMIT 1
                    """,
                    (
                        delivery_id,
                        repository_id,
                        event_name,
                        ref_name,
                        commit_sha,
                        delivery_id,
                    ),
                )
                existing = cur.fetchone()
        return DeliveryClaim(
            False,
            str(existing["delivery_id"]),
            str(existing["job_id"]),
            str(existing["status"]),
        )

    def mark_github_delivery(self, delivery_id: str, *, status: str, failure_reason: str | None = None) -> None:
        if status not in {"dispatched", "ignored", "failed"}:
            raise ValueError(f"Unsupported GitHub delivery status: {status}")
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE github_webhook_deliveries
                    SET status = %s,
                        failure_reason = %s,
                        handled_at = now()
                    WHERE delivery_id = %s
                    """,
                    (status, failure_reason, delivery_id),
                )


__all__ = [
    "DeliveryClaim",
    "PostgresEdgeSecurityRepository",
    "RateLimitDecision",
    "RateLimitRule",
]
