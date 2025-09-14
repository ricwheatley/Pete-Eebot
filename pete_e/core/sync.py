"""
Daily sync orchestrator for Pete-Eebot.

- Intended to be run from cron at 03:00 local time.
- Backfills the last `days` calendar days on each run, so missed runs get filled.
- Upserts daily summaries into the DAL (Postgres or JSON fallback).
- Inserts strength logs from Wger per set.
- Calculates body age per day for logging or future persistence.

This module is side effect free except for DAL writes and client API calls.
"""

from __future__ import annotations

import sys
import time
from datetime import date, timedelta
from typing import Dict, List, Tuple

# Centralised components
from pete_e.config import settings
from pete_e.infra import log_utils

# Refactored clients and modules
from pete_e.core.withings_client import WithingsClient
from integrations.wger.client import WgerClient
from pete_e.core import apple_client, body_age, lift_log

# DAL contract and implementations
from pete_e.data_access.dal import DataAccessLayer
from pete_e.data_access.json_dal import JsonDal

try:
    from pete_e.data_access.postgres_dal import PostgresDal  # type: ignore
except Exception:  # pragma: no cover - optional import
    PostgresDal = None  # type: ignore


DEFAULT_BACKFILL_DAYS = 7
DEFAULT_RETRIES = 3
DEFAULT_RETRY_DELAY_SECS = 60


def _get_dal() -> DataAccessLayer:
    """
    Choose a DAL based on environment.
    - Production with DATABASE_URL and importable PostgresDal uses PostgresDal.
    - Otherwise fall back to JsonDal.
    """
    if (
        PostgresDal
        and getattr(settings, "DATABASE_URL", None)
        and getattr(settings, "ENVIRONMENT", "").lower() == "production"
    ):
        try:
            return PostgresDal()  # type: ignore[operator]
        except Exception as e:  # pragma: no cover - fallback path
            log_utils.log_message(
                f"[sync] Postgres DAL init failed: {e}. Falling back to JSON.", "WARN"
            )
    return JsonDal()


def _safe_get_withings_summary(client: WithingsClient, target_day: date) -> Dict:
    try:
        return client.get_summary(target_date=target_day)
    except Exception as e:
        log_utils.log_message(
            f"[sync] Withings fetch failed for {target_day.isoformat()}: {e}", "ERROR"
        )
        return {}


def _safe_get_apple_summary(target_iso: str) -> Dict:
    try:
        # Keep the same call signature you already use
        return apple_client.get_apple_summary({"date": target_iso})
    except Exception as e:
        log_utils.log_message(
            f"[sync] Apple fetch failed for {target_iso}: {e}", "ERROR"
        )
        return {}


def _safe_get_wger_logs(client: WgerClient, days: int) -> Dict[str, List[Dict]]:
    """
    Fetch logs once for the whole window.
    Returns a mapping of ISO date -> list of log dicts for that date.
    """
    try:
        data = client.get_logs(days=days)
        # Be defensive about the shape
        if not isinstance(data, dict):
            log_utils.log_message(
                f"[sync] Wger logs unexpected shape, expected dict got {type(data)}. Treating as empty.", "WARN"
            )
            return {}
        log_utils.log_message(
            f"[sync] Wger logs fetched for last {days} days.", "INFO"
        )
        return data
    except Exception as e:
        log_utils.log_message(f"[sync] Wger fetch failed: {e}", "ERROR")
        return {}


def _upsert_daily_summary(dal: DataAccessLayer, the_day: date, withings: Dict, apple: Dict) -> None:
    try:
        dal.save_daily_summary({"withings": withings, "apple": apple}, the_day)
        log_utils.log_message(
            f"[sync] Upserted daily summary for {the_day.isoformat()}", "INFO"
        )
    except Exception as e:
        log_utils.log_message(
            f"[sync] Failed to save daily summary for {the_day.isoformat()}: {e}", "ERROR"
        )


def _insert_wger_logs_for_day(dal: DataAccessLayer, logs: List[Dict], the_day: date) -> None:
    if not logs:
        return
    inserted = 0
    for log in logs:
        try:
            lift_log.append_log_entry(
                dal=dal,
                exercise_id=log.get("exercise_id"),
                weight=log.get("weight"),
                reps=log.get("reps"),
                sets=log.get("sets"),
                rir=log.get("rir"),
                # Use the actual day we are processing
                log_date=the_day,
            )
            inserted += 1
        except Exception as e:
            log_utils.log_message(
                f"[sync] Failed to save strength log for {the_day.isoformat()}: {e}. Payload={log}", "ERROR"
            )
    log_utils.log_message(
        f"[sync] Inserted {inserted} Wger set logs for {the_day.isoformat()}", "INFO"
    )


def _calculate_and_log_body_age(withings: Dict, apple: Dict, the_day: date) -> None:
    try:
        # Keep your current profile usage. You can wire this to settings later if desired.
        result = body_age.calculate_body_age([withings, apple], profile={"age": 40})
        log_utils.log_message(
            f"[sync] Body Age for {the_day.isoformat()}: {result}", "INFO"
        )
        # If you add DAL persistence for body age in future, call it here.
    except Exception as e:
        log_utils.log_message(
            f"[sync] Body Age calculation failed for {the_day.isoformat()}: {e}", "ERROR"
        )


def run_sync(dal: DataAccessLayer, days: int = DEFAULT_BACKFILL_DAYS) -> Tuple[bool, List[str]]:
    """
    Run a backfilling sync for the previous `days` calendar days.

    Example: on 2025-09-14 at 03:00, with days=7, this processes 2025-09-07 to 2025-09-13 inclusive.

    Returns:
        (success, failed_sources)
        - success is True if no upstream sources failed across the whole window
        - failed_sources is a unique list of source names that had at least one failure
    """
    today = date.today()
    window_desc = f"{(today - timedelta(days=days)).isoformat()}..{(today - timedelta(days=1)).isoformat()}"
    log_utils.log_message(f"[sync] Starting backfill sync for {days} days, window {window_desc}", "INFO")

    # Instantiate clients once
    withings_client = WithingsClient()
    wger_client = WgerClient()

    # Fetch Wger logs once for the range
    wger_data = _safe_get_wger_logs(wger_client, days=days)

    failed_sources: List[str] = []

    # Process from oldest to newest for deterministic behaviour
    for offset in range(days, 0, -1):
        target_day = today - timedelta(days=offset)
        target_iso = target_day.isoformat()
        log_utils.log_message(f"[sync] Processing {target_iso}", "INFO")

        withings_data = _safe_get_withings_summary(withings_client, target_day)
        if not withings_data and "Withings" not in failed_sources:
            failed_sources.append("Withings")

        apple_data = _safe_get_apple_summary(target_iso)
        if not apple_data and "Apple" not in failed_sources:
            failed_sources.append("Apple")

        _upsert_daily_summary(dal, target_day, withings_data, apple_data)

        # Wger logs may be keyed by ISO string dates
        day_logs = wger_data.get(target_iso, [])
        if not wger_data and "Wger" not in failed_sources:
            # Only mark as failed if the entire fetch failed, not if a specific day is empty
            failed_sources.append("Wger")
        _insert_wger_logs_for_day(dal, day_logs, target_day)

        # Optional calculation - logged for observability
        _calculate_and_log_body_age(withings_data, apple_data, target_day)

    if failed_sources:
        log_utils.log_message(
            f"[sync] Completed with failures. Sources with at least one error: {sorted(set(failed_sources))}", "WARN"
        )
        return False, sorted(set(failed_sources))

    log_utils.log_message(f"[sync] Successfully completed backfill sync for {window_desc}", "INFO")
    return True, []


def run_sync_with_retries(
    dal: DataAccessLayer | None = None,
    retries: int = DEFAULT_RETRIES,
    delay: int = DEFAULT_RETRY_DELAY_SECS,
    days: int = DEFAULT_BACKFILL_DAYS,
) -> bool:
    """
    Run the sync with simple retries. Useful when scheduled by cron where transient
    upstream or network issues are common around nightly windows.

    Args:
        dal: optional DAL instance. If None, selects one based on environment.
        retries: number of attempts before giving up.
        delay: seconds to wait between attempts.
        days: backfill window length.

    Returns:
        True if a run completed without any source failures, else False.
    """
    dal = dal or _get_dal()
    for attempt in range(1, max(1, retries) + 1):
        success, failed = run_sync(dal=dal, days=days)
        if success:
            return True
        if attempt < retries:
            log_utils.log_message(
                f"[sync] Attempt {attempt}/{retries} had failures {failed}. Retrying in {delay}s...",
                "WARN",
            )
            time.sleep(max(1, delay))
    log_utils.log_message(f"[sync] All {retries} attempts finished with failures.", "ERROR")
    return False


def _main() -> int:
    """
    CLI entry point so this module can be executed directly by cron.

    Environment control:
      - settings.ENVIRONMENT
      - settings.DATABASE_URL
      - optional future knobs for days, retries, delay if you add them to settings
    """
    days = getattr(settings, "SYNC_BACKFILL_DAYS", DEFAULT_BACKFILL_DAYS)
    retries = getattr(settings, "SYNC_RETRIES", DEFAULT_RETRIES)
    delay = getattr(settings, "SYNC_RETRY_DELAY_SECS", DEFAULT_RETRY_DELAY_SECS)

    ok = run_sync_with_retries(
        dal=None,
        retries=retries,
        delay=delay,
        days=days,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_main())
