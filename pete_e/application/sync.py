"""
Daily sync orchestrator for Pete-Eebot.

This script acts as a simple entry point for the synchronization process,
which is orchestrated by the Orchestrator class. It's intended to be
run from the main CLI.
"""
from typing import Callable, Iterable, Optional, Tuple

from tenacity import (
    RetryCallState,
    RetryError,
    Retrying,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

from pete_e.application.orchestrator import Orchestrator
from pete_e.infrastructure import log_utils

DEFAULT_RETRIES = 3
DEFAULT_RETRY_DELAY_SECS = 60


class SyncAttemptFailedError(RuntimeError):
    """Represents a failed sync attempt that should be retried."""

    def __init__(self, failed_sources: Optional[Iterable[str]] = None) -> None:
        super().__init__("Sync attempt failed.")
        self.failed_sources = list(failed_sources or [])


def _run_with_retry(
    execute: Callable[[], Tuple[bool, Iterable[str]]],
    max_attempts: int,
    base_delay: int,
    label: str,
) -> bool:
    def _sync_once() -> bool:
        success, failures = execute()
        if success:
            return True
        raise SyncAttemptFailedError(failures)

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
        return True
    except RetryError as exc:
        last_exception = exc.last_attempt.exception()
        message = f"All {max_attempts} {label} attempts finished with failures."

        if isinstance(last_exception, SyncAttemptFailedError):
            if last_exception.failed_sources:
                message += f" Failures in: {last_exception.failed_sources}."
        elif last_exception is not None:
            message += f" Last exception: {last_exception}."

        log_utils.log_message(message, "ERROR")
        return False


def run_sync_with_retries(
    days: int,
    retries: int = DEFAULT_RETRIES,
    delay: int = DEFAULT_RETRY_DELAY_SECS,
) -> bool:
    """Run the full multi-source sync via the Orchestrator with retries."""

    orchestrator = Orchestrator()
    max_attempts = max(1, retries)
    base_delay = max(1, delay)

    return _run_with_retry(
        execute=lambda: orchestrator.run_daily_sync(days=days),
        max_attempts=max_attempts,
        base_delay=base_delay,
        label="Sync",
    )


def run_withings_only_with_retries(
    days: int,
    retries: int = DEFAULT_RETRIES,
    delay: int = DEFAULT_RETRY_DELAY_SECS,
) -> bool:
    """Run the Withings-only sync with the same retry semantics as the full sync."""

    orchestrator = Orchestrator()
    max_attempts = max(1, retries)
    base_delay = max(1, delay)

    return _run_with_retry(
        execute=lambda: orchestrator.run_withings_only_sync(days=days),
        max_attempts=max_attempts,
        base_delay=base_delay,
        label="Withings-only sync",
    )