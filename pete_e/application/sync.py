"""
Daily sync orchestrator for Pete-Eebot.

This script acts as a simple entry point for the synchronization process,
which is orchestrated by the Orchestrator class. It's intended to be
run from the main CLI.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Tuple, TYPE_CHECKING, Union

from tenacity import (
    RetryCallState,
    RetryError,
    Retrying,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

from pete_e.infrastructure import log_utils

if TYPE_CHECKING:
    from pete_e.application.orchestrator import Orchestrator as OrchestratorType
else:
    Orchestrator = None  # type: ignore

DEFAULT_RETRIES = 3
DEFAULT_RETRY_DELAY_SECS = 60


SUMMARY_FAILURE_NOTES = {
    "Withings": "Withings data unavailable {window}",
}

@dataclass
class SyncResult:
    """Aggregate outcome of a sync run after retries complete."""

    success: bool
    attempts: int
    failed_sources: List[str]
    source_statuses: Dict[str, str]
    label: str
    undelivered_alerts: List[str]

    def summary_line(self, *, days: int) -> str:
        statuses = self.source_statuses or {}
        if statuses:
            status_tokens = [f"{name}={value}" for name, value in statuses.items()]
            statuses_fragment = ", ".join(status_tokens)
        else:
            statuses_fragment = "sources=unreported"
        verdict = "success" if self.success else "failed"
        lines = [
            f"Sync summary: run={self.label} | days={days} | attempts={self.attempts} | "
            f"result={verdict} | {statuses_fragment}"
        ]
        lines.extend(self._build_source_notes(days=days))
        if self.undelivered_alerts:
            lines.append("Alerts pending delivery:")
            lines.extend(f"- {alert}" for alert in self.undelivered_alerts)
        return "\n".join(lines)

    def _build_source_notes(self, *, days: int) -> List[str]:
        if not self.source_statuses:
            return []
        window = "today" if days == 1 else f"across last {days} days"
        notes: List[str] = []
        for name, status in sorted(self.source_statuses.items()):
            if status != "failed":
                continue
            template = SUMMARY_FAILURE_NOTES.get(name)
            if template:
                notes.append(template.format(window=window))
        return notes

    def log_level(self) -> str:
        return "INFO" if self.success else "ERROR"


class SyncAttemptFailedError(RuntimeError):
    """Represents a failed sync attempt that should be retried."""

    def __init__(
        self,
        failed_sources: Optional[Iterable[str]] = None,
        source_statuses: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__("Sync attempt failed.")
        self.failed_sources = list(failed_sources or [])
        self.source_statuses = dict(source_statuses or {})


def _build_orchestrator():
    global Orchestrator
    if callable(Orchestrator):  # patched in tests
        return Orchestrator()  # type: ignore[misc]
    from pete_e.application.orchestrator import Orchestrator as _Orchestrator
    Orchestrator = _Orchestrator  # type: ignore
    return _Orchestrator()


def _build_failure_message(
    label: str,
    max_attempts: int,
    failures: Iterable[str],
    extra: Optional[BaseException] = None,
) -> str:
    """Create a consistent failure summary for retry exhaustion."""

    failure_list = list(failures)
    message = f"All {max_attempts} {label} attempts finished with failures."
    if failure_list:
        message += f" Failures in: {failure_list}."
    if extra is not None:
        message += f" Last exception: {extra}."
    return message


def _run_with_retry(
    execute: Callable[
        [],
        Union[
            Tuple[bool, Iterable[str], Dict[str, str]],
            Tuple[bool, Iterable[str], Dict[str, str], Iterable[str]],
        ],
    ],
    max_attempts: int,
    base_delay: int,
    label: str,
    summary_name: Optional[str] = None,
) -> SyncResult:
    summary_label = summary_name or label
    attempts = 0
    last_failures: List[str] = []
    last_statuses: Dict[str, str] = {}
    last_alerts: List[str] = []

    def _sync_once() -> bool:
        nonlocal attempts, last_failures, last_statuses
        attempts += 1
        result = execute()
        if len(result) == 4:
            success, failures, statuses, alerts = result  # type: ignore[misc]
        else:
            success, failures, statuses = result  # type: ignore[misc]
            alerts = []
        last_failures = list(failures)
        last_statuses = dict(statuses or {})
        last_alerts = list(alerts)
        if success:
            return True
        raise SyncAttemptFailedError(last_failures, last_statuses)

    def _before_sleep(retry_state: RetryCallState) -> None:
        wait_time = getattr(retry_state.next_action, "sleep", base_delay)
        wait_time_str = f"{wait_time:.2f}".rstrip("0").rstrip(".") or "0"
        exception = retry_state.outcome.exception()

        if isinstance(exception, SyncAttemptFailedError):
            reason = f"failures in: {exception.failed_sources}"
        else:
            reason = f"exception: {exception}"

        log_utils.log_message(
            (
                f"{label} attempt {retry_state.attempt_number}/{max_attempts} "
                f"had {reason}. Retrying in {wait_time_str}s..."
            ),
            "WARN",
        )

    retryer = Retrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(
            multiplier=base_delay,
            min=base_delay,
            max=base_delay * 8,
        )
        + wait_random(0, base_delay),
        before_sleep=_before_sleep,
        reraise=True,
    )

    try:
        retryer(_sync_once)
        unique_failures = sorted(set(last_failures))
        return SyncResult(
            success=True,
            attempts=attempts,
            failed_sources=unique_failures,
            source_statuses=dict(last_statuses),
            label=summary_label,
            undelivered_alerts=list(last_alerts),
        )
    except RetryError as exc:
        last_exception = exc.last_attempt.exception()

        if isinstance(last_exception, SyncAttemptFailedError):
            last_failures = last_exception.failed_sources or []
            if last_exception.source_statuses:
                last_statuses.update(last_exception.source_statuses)
            message = _build_failure_message(label, max_attempts, last_failures)
        elif last_exception is not None:
            last_failures = [str(last_exception)]
            message = _build_failure_message(label, max_attempts, last_failures, last_exception)
        else:
            last_failures = []
            message = _build_failure_message(label, max_attempts, last_failures)

        log_utils.log_message(message, "ERROR")
        unique_failures = sorted(set(last_failures))
        return SyncResult(
            success=False,
            attempts=attempts,
            failed_sources=unique_failures,
            source_statuses=dict(last_statuses),
            label=summary_label,
            undelivered_alerts=list(last_alerts),
        )

    except SyncAttemptFailedError as exc:
        last_failures = exc.failed_sources or []
        if exc.source_statuses:
            last_statuses.update(exc.source_statuses)
        message = _build_failure_message(label, max_attempts, last_failures)
        log_utils.log_message(message, "ERROR")
        unique_failures = sorted(set(last_failures))
        return SyncResult(
            success=False,
            attempts=attempts,
            failed_sources=unique_failures,
            source_statuses=dict(last_statuses),
            label=summary_label,
            undelivered_alerts=list(last_alerts),
        )




def run_sync_with_retries(
    days: int,
    retries: int = DEFAULT_RETRIES,
    delay: int = DEFAULT_RETRY_DELAY_SECS,
) -> SyncResult:
    """Run the full multi-source sync via the Orchestrator with retries."""

    orchestrator = _build_orchestrator()
    max_attempts = max(1, retries)
    base_delay = max(1, delay)

    result = _run_with_retry(
        execute=lambda: orchestrator.run_daily_sync(days=days),
        max_attempts=max_attempts,
        base_delay=base_delay,
        label="Sync",
        summary_name="daily",
    )
    log_utils.log_message(result.summary_line(days=days), result.log_level())
    return result


def run_withings_only_with_retries(
    days: int,
    retries: int = DEFAULT_RETRIES,
    delay: int = DEFAULT_RETRY_DELAY_SECS,
) -> SyncResult:
    """Run the Withings-only sync with the same retry semantics as the full sync."""

    orchestrator = _build_orchestrator()
    max_attempts = max(1, retries)
    base_delay = max(1, delay)

    result = _run_with_retry(
        execute=lambda: orchestrator.run_withings_only_sync(days=days),
        max_attempts=max_attempts,
        base_delay=base_delay,
        label="Withings-only sync",
        summary_name="withings-only",
    )
    log_utils.log_message(result.summary_line(days=days), result.log_level())
    return result
