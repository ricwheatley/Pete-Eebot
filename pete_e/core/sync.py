"""
Daily sync orchestrator for Pete-Eebot.

This script acts as a simple entry point for the synchronization process,
which is orchestrated by the Orchestrator class. It's intended to be
run from the main CLI.
"""
import time

from pete_e.core.orchestrator import Orchestrator
from pete_e.infra import log_utils

DEFAULT_RETRIES = 3
DEFAULT_RETRY_DELAY_SECS = 60

def run_sync_with_retries(
    days: int,
    retries: int = DEFAULT_RETRIES,
    delay: int = DEFAULT_RETRY_DELAY_SECS,
) -> bool:
    """
    Run the sync via the Orchestrator with a simple retry mechanism.
    """
    orchestrator = Orchestrator()
    for attempt in range(1, max(1, retries) + 1):
        success, failed_sources = orchestrator.run_daily_sync(days=days)
        if success:
            return True

        if attempt < retries:
            log_utils.log_message(
                f"Sync attempt {attempt}/{retries} had failures in: {failed_sources}. "
                f"Retrying in {delay}s...", "WARN"
            )
            time.sleep(max(1, delay))

    log_utils.log_message(
        f"All {retries} sync attempts finished with failures.", "ERROR"
    )
    return False