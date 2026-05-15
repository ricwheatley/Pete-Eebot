"""Alert event wiring for operational incidents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import threading
import time
from typing import Any, Mapping

from pete_e import observability
from pete_e.config import get_env
from pete_e.infrastructure import log_utils, telegram_sender

ALERT_STALE_INGEST = "stale_ingest"
ALERT_AUTH_EXPIRY = "auth_expiry"
ALERT_REPEATED_FAILURES = "repeated_failures"

SEVERITY_P1 = "P1"
SEVERITY_P2 = "P2"
SEVERITY_P3 = "P3"

FAILURE_OUTCOMES = {"failed", "timeout"}
AUTH_EXPIRY_MARKERS = (
    "expired",
    "expire",
    "invalid_grant",
    "invalid refresh",
    "unauthorized",
    "401",
    "reauth",
)


@dataclass(frozen=True)
class AlertEvent:
    alert_type: str
    severity: str
    title: str
    summary: str
    dedupe_key: str
    context: Mapping[str, Any] | None = None


_lock = threading.Lock()
_last_emitted_at: dict[str, float] = {}
_failure_streaks: dict[str, int] = {}


def reset_alert_state() -> None:
    """Clear in-process dedupe and streak state. Intended for tests."""

    with _lock:
        _last_emitted_at.clear()
        _failure_streaks.clear()


def emit_alert(event: AlertEvent) -> bool:
    """Emit an alert log/metric/notification event, with best-effort delivery."""

    dedupe_seconds = _float_env("PETEEEBOT_ALERT_DEDUPE_SECONDS", 3600.0)
    now = time.monotonic()
    with _lock:
        last_emitted = _last_emitted_at.get(event.dedupe_key)
        if last_emitted is not None and now - last_emitted < dedupe_seconds:
            observability.record_alert_event(
                alert_type=event.alert_type,
                severity=event.severity,
                outcome="deduped",
            )
            return False
        _last_emitted_at[event.dedupe_key] = now

    observability.record_alert_event(alert_type=event.alert_type, severity=event.severity)
    observability.set_alert_active(alert_type=event.alert_type, severity=event.severity, active=True)
    log_utils.log_event(
        event="alert_event",
        message=f"alert {event.alert_type} {event.severity}",
        tag="ALERT",
        level=_level_for_severity(event.severity),
        alert_type=event.alert_type,
        severity=event.severity,
        title=event.title,
        outcome="emitted",
        dedupe_key=event.dedupe_key,
        summary={"message": event.summary, **dict(event.context or {})},
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    if not _bool_env("PETEEEBOT_ALERT_TELEGRAM_ENABLED", True):
        return True

    try:
        telegram_sender.send_alert(_format_alert_message(event))
    except Exception as exc:  # pragma: no cover - notification must never break callers.
        log_utils.log_event(
            event="alert_delivery",
            message="alert notification delivery failed",
            tag="ALERT",
            level="WARNING",
            alert_type=event.alert_type,
            severity=event.severity,
            outcome="failed",
            summary={"error": str(exc)},
        )
    return True


def emit_stale_ingest_if_needed(
    *,
    source: str,
    stale_days: int | None,
    last_sync_at: str | None,
    completeness_pct: float | None = None,
) -> bool:
    threshold_days = _int_env(
        "PETEEEBOT_STALE_INGEST_ALERT_DAYS",
        _int_env("APPLE_MAX_STALE_DAYS", 3),
    )
    is_stale = stale_days is None or stale_days >= threshold_days
    if not is_stale:
        return False

    severity = SEVERITY_P1 if stale_days is None or stale_days >= 7 else SEVERITY_P2
    stale_label = "unknown" if stale_days is None else str(stale_days)
    return emit_alert(
        AlertEvent(
            alert_type=ALERT_STALE_INGEST,
            severity=severity,
            title=f"{source} ingest is stale",
            summary=(
                f"{source} last data date is {last_sync_at or 'missing'} "
                f"({stale_label} stale days)."
            ),
            dedupe_key=f"{ALERT_STALE_INGEST}:{source}",
            context={
                "source": source,
                "stale_days": stale_days,
                "last_sync_at": last_sync_at,
                "completeness_pct": completeness_pct,
                "threshold_days": threshold_days,
            },
        )
    )


def emit_auth_expiry_if_needed(*, provider: str, detail: str, context: Mapping[str, Any] | None = None) -> bool:
    normalized = str(detail or "").strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    if not any(marker in lowered for marker in AUTH_EXPIRY_MARKERS):
        return False

    severity = SEVERITY_P1 if "refresh" in lowered or "invalid_grant" in lowered else SEVERITY_P2
    return emit_alert(
        AlertEvent(
            alert_type=ALERT_AUTH_EXPIRY,
            severity=severity,
            title=f"{provider} authorization needs attention",
            summary=f"{provider} health check reported: {normalized}",
            dedupe_key=f"{ALERT_AUTH_EXPIRY}:{provider}",
            context={"provider": provider, "detail": normalized, **dict(context or {})},
        )
    )


def record_operation_outcome(
    *,
    operation: str,
    outcome: str,
    job_id: str | None = None,
    context: Mapping[str, Any] | None = None,
) -> bool:
    normalized_outcome = str(outcome or "").lower()
    threshold = _int_env("PETEEEBOT_REPEATED_FAILURE_ALERT_THRESHOLD", 3)
    if threshold <= 0:
        return False

    with _lock:
        if normalized_outcome not in FAILURE_OUTCOMES:
            _failure_streaks.pop(operation, None)
            return False
        streak = _failure_streaks.get(operation, 0) + 1
        _failure_streaks[operation] = streak

    if streak < threshold:
        return False

    severity = SEVERITY_P1 if streak >= max(threshold * 2, threshold + 2) else SEVERITY_P2
    return emit_alert(
        AlertEvent(
            alert_type=ALERT_REPEATED_FAILURES,
            severity=severity,
            title=f"{operation} is repeatedly failing",
            summary=f"{operation} has {streak} consecutive failed or timed-out runs.",
            dedupe_key=f"{ALERT_REPEATED_FAILURES}:{operation}",
            context={
                "operation": operation,
                "outcome": normalized_outcome,
                "failure_streak": streak,
                "threshold": threshold,
                "job_id": job_id,
                **dict(context or {}),
            },
        )
    )


def _format_alert_message(event: AlertEvent) -> str:
    return "\n".join(
        [
            f"{event.severity} {event.title}",
            event.summary,
            f"type={event.alert_type}",
            "Runbook: docs/runtime_deploy_runbook.md#9-alert-response-playbooks",
        ]
    )


def _level_for_severity(severity: str) -> str:
    return "CRITICAL" if severity == SEVERITY_P1 else "ERROR" if severity == SEVERITY_P2 else "WARNING"


def _bool_env(name: str, default: bool) -> bool:
    value = get_env(name, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_env(name: str, default: int) -> int:
    try:
        return int(get_env(name, default))
    except (TypeError, ValueError):
        return int(default)


def _float_env(name: str, default: float) -> float:
    try:
        return float(get_env(name, default))
    except (TypeError, ValueError):
        return float(default)
