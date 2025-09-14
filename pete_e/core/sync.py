"""
Daily sync orchestrator for Pete-Eebot.

- Intended to be run from cron at 03:00 local time.
- Backfills the last `days` calendar days on each run, so missed runs get filled.
- Upserts daily summaries into the DAL (Postgres or JSON fallback).
- Inserts strength logs from Wger per set.
- Calculates body age per day from DB and persists.
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
from pete_e.core import apple_client, lift_log

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
    """Choose a DAL based on environment."""
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
    """Fetch Withings summary for a specific day using days_back offset."""
    try:
        days_back = (date.today() - target_day).days
        return client.get_summary(days_back=days_back)
    except Exception as e:
        log_utils.log_message(
            f"[sync] Withings fetch failed for {target_day.isoformat()}: {e}", "ERROR"
        )
        return {}


def _safe_get_apple_summary(target_iso: str) -> Dict:
    try:
        return apple_client.get_apple_summary({"date": target_iso})
    except Exception as e:
        log_utils.log_message(
            f"[sync] Apple fetch failed for {target_iso}: {e}", "ERROR"
        )
        return {}


def _safe_get_wger_logs(client: WgerClient, days: int):
    try:
        data = client.get_logs(days=days)
        if isinstance(data, list):
            # Normalise to dict keyed by date
            out: Dict[str, List[Dict]] = {}
            for log in data:
                d = log.get("date")
                out.setdefault(d, []).append(log)
            log_utils.log_message(f"[sync] Normalised {len(data)} Wger logs", "INFO")
            return out
        elif isinstance(data, dict):
            return data
        else:
            log_utils.log_message(
                f"[sync] Wger logs unexpected shape: {type(data)}", "WARN"
            )
            return {}
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
    # Roll up strength volume into daily_summary
    try:
        dal.update_strength_volume(the_day)
    except Exception as e:
        log_utils.log_message(
            f"[sync] Failed to update strength volume for {the_day.isoformat()}: {e}", "ERROR"
        )


def _calculate_and_save_body_age(dal: DataAccessLayer, the_day: date) -> None:
    """Calculate body age from DB history and persist into both body_age_log and daily_summary."""
    try:
        window_start = the_day - timedelta(days=6)
        dal.calculate_and_save_body_age(window_start, the_day, profile={"age": 40})
    except Exception as e:
        log_utils.log_message(
            f"[sync] Body Age calculation failed for {the_day.isoformat()}: {e}", "ERROR"
        )


def run_sync(dal: DataAccessLayer, days: int = DEFAULT_BACKFILL_DAYS) -> Tuple[bool, List[str]]:
    """
    Run a backfilling sync for the previous `days` calendar days.
    """
    today = date.today()
    window_desc = f"{(today - timedelta(days=days)).isoformat()}..{(today - timedelta(days=1)).isoformat()}"
    log_utils.log_message(f"[sync] Starting backfill sync for {days} days, window {window_desc}", "INFO")

    withings_client = WithingsClient()
    wger_client = WgerClient()

    # Fetch Wger logs once for the range
    wger_data = _safe_get_wger_logs(wger_client, days=days)

    failed_sources: List[str] = []

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

        day_logs = wger_data.get(target_iso, [])
        if not wger_data and "Wger" not in failed_sources:
            failed_sources.append("Wger")
        _insert_wger_logs_for_day(dal, day_logs, target_day)

        _calculate_and_save_body_age(dal, target_day)

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
    """Run the sync with simple retries."""
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
    """CLI entry point so this module can be executed directly by cron."""
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
