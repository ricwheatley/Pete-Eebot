"""In-memory test double for the PostgreSQL edge-security repository port."""

from __future__ import annotations

from dataclasses import dataclass
import math
import threading
import time

from pete_e.infrastructure.edge_security_repository import (
    DeliveryClaim,
    RateLimitDecision,
    RateLimitRule,
)


@dataclass
class _Counter:
    started_at: float
    count: int = 0
    next_allowed_at: float = 0.0
    locked_until: float = 0.0


class InMemoryEdgeSecurityRepository:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, str], _Counter] = {}
        self.deliveries: dict[str, dict[str, str]] = {}

    @staticmethod
    def _active(rules):
        return tuple(rule for rule in rules if rule.max_requests > 0 and rule.window_seconds > 0)

    def _decision(self, rule: RateLimitRule, now: float):
        counter = self._counters.get((rule.scope, rule.subject))
        if counter is None:
            return None
        if counter.locked_until > now:
            return RateLimitDecision("login_locked", max(1, math.ceil(counter.locked_until - now)))
        if counter.next_allowed_at > now:
            return RateLimitDecision("login_backoff", max(1, math.ceil(counter.next_allowed_at - now)))
        if now - counter.started_at < rule.window_seconds and counter.count >= rule.max_requests:
            return RateLimitDecision(
                "rate_limited",
                max(1, math.ceil(rule.window_seconds - (now - counter.started_at))),
            )
        return None

    def check_rate_limits(self, rules):
        with self._lock:
            now = time.monotonic()
            for rule in self._active(rules):
                decision = self._decision(rule, now)
                if decision is not None:
                    return decision
        return None

    def consume_rate_limits(self, rules):
        with self._lock:
            now = time.monotonic()
            active = self._active(rules)
            for rule in active:
                decision = self._decision(rule, now)
                if decision is not None:
                    return decision
            for rule in active:
                key = (rule.scope, rule.subject)
                counter = self._counters.get(key)
                if counter is None or now - counter.started_at >= rule.window_seconds:
                    counter = _Counter(started_at=now)
                    self._counters[key] = counter
                counter.count += 1
                counter.next_allowed_at = 0.0
                counter.locked_until = 0.0
        return None

    def record_failures(self, rules):
        result = None
        with self._lock:
            now = time.monotonic()
            for rule in self._active(rules):
                key = (rule.scope, rule.subject)
                counter = self._counters.get(key)
                if counter is None or now - counter.started_at >= rule.window_seconds:
                    counter = _Counter(started_at=now)
                    self._counters[key] = counter
                counter.count += 1
                if counter.count >= rule.max_requests and rule.lockout_seconds > 0:
                    counter.locked_until = now + rule.lockout_seconds
                    counter.next_allowed_at = counter.locked_until
                    decision = RateLimitDecision("login_locked", max(1, math.ceil(rule.lockout_seconds)))
                    if result is None or decision.retry_after_seconds > result.retry_after_seconds:
                        result = decision
                elif rule.backoff_base_seconds > 0:
                    delay = rule.backoff_base_seconds * (2 ** max(0, counter.count - 1))
                    if rule.lockout_seconds > 0:
                        delay = min(delay, rule.lockout_seconds)
                    counter.next_allowed_at = now + delay
        return result

    def clear_rate_limits(self, rules):
        with self._lock:
            for rule in self._active(rules):
                self._counters.pop((rule.scope, rule.subject), None)

    def claim_github_delivery(
        self,
        *,
        delivery_id: str,
        repository_id: int,
        event_name: str,
        ref_name: str,
        commit_sha: str,
        job_id: str,
    ):
        with self._lock:
            existing = self.deliveries.get(delivery_id)
            if existing is None:
                existing = next(
                    (
                        delivery
                        for delivery in self.deliveries.values()
                        if delivery["repository_id"] == repository_id
                        and delivery["event_name"] == event_name
                        and delivery["ref_name"] == ref_name
                        and delivery["commit_sha"] == commit_sha
                    ),
                    None,
                )
            if existing is not None:
                return DeliveryClaim(False, delivery_id, existing["job_id"], existing["status"])
            self.deliveries[delivery_id] = {
                "repository_id": repository_id,
                "event_name": event_name,
                "ref_name": ref_name,
                "commit_sha": commit_sha,
                "job_id": job_id,
                "status": "accepted",
            }
            return DeliveryClaim(True, delivery_id, job_id, "accepted")

    def mark_github_delivery(self, delivery_id: str, *, status: str, failure_reason=None):
        with self._lock:
            self.deliveries[delivery_id]["status"] = status
            if failure_reason:
                self.deliveries[delivery_id]["failure_reason"] = str(failure_reason)
