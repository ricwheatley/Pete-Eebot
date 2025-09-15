"""
Daily sync orchestrator for Pete-Eebot.

- Intended to be run from cron at 03:00 local time.
- Backfills the last `days` calendar days on each run, so missed runs get filled.
- Persists source metrics into normalized tables:
  * Withings → withings_daily
  * Apple → apple_daily
  * Wger → wger_logs
  * Body age → body_age_daily
- `daily_summary` is a view and never written to directly.
"""

import sys
import time
from datetime import date, timedelta
from typing import List, Tuple, Dict

from pete_e.config import settings
from pete_e.infra import log_utils

# Refactored clients
from pete_e.core.withings_client import WithingsClient
from integrations.wger.client import WgerClient
from pete_e.core import apple_client
from pete_e.core import body_age

# DAL contract + Postgres implementation
from pete_e.data_access.dal import DataAccessLayer
from pete_e.data_access.postgres_dal import PostgresDal


DEFAULT_BACKFILL_DAYS = 7
DEFAULT_RETRIES = 3
DEFAULT_RETRY_DELAY_SECS = 60


def _safe_get_withings_summary(client: WithingsClient, target_day: date) -> Dict:
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


def _safe_get_wger_logs(client: WgerClient, days: int) -> Dict[str, List[Dict]]:
    try:
        data = client.fetch_logs(days=days)  # NOTE: renamed from get_logs → fetch_logs
        if isinstance(data, list):
            out: Dict[str, List[Dict]] = {}
            for log in data:
                d = log.get("date")
                out.setdefault(d, []).append(log)
            return out
        elif isinstance(data, dict):
            return data
        else:
            log_utils.log_message(f"[sync] Unexpected Wger log format: {type(data)}", "WARN")
            return {}
    except Exception as e:
        log_utils.log_message(f"[sync] Wger fetch failed: {e}", "ERROR")
        return {}


def run_sync(dal: DataAccessLayer, days: int = DEFAULT_BACKFILL_DAYS) -> Tuple[bool, List[str]]:
    """
    Run a backfilling sync for the previous `days` calendar days.
    """
    today = date.today()
    window_desc = f"{(today - timedelta(days=days)).isoformat()}..{(today - timedelta(days=1)).isoformat()}"
    log_utils.log_message(f"[sync] Starting backfill sync for {days} days, window {window_desc}", "INFO")

    withings_client = WithingsClient()
    wger_client = WgerClient()

    # Fetch Wger logs once
    wger_data = _safe_get_wger_logs(wger_client, days=days)

    failed_sources: List[str] = []

    for offset in range(days, 0, -1):
        target_day = today - timedelta(days=offset)
        target_iso = target_day.isoformat()
        log_utils.log_message(f"[sync] Processing {target_iso}", "INFO")

        # --- Withings ---
        withings_data = _safe_get_withings_summary(withings_client, target_day)
        if withings_data:
            dal.save_withings_daily(
                day=target_day,
                weight_kg=withings_data.get("weight"),
                body_fat_pct=withings_data.get("fat_percent"),
            )
        else:
            failed_sources.append("Withings")

        # --- Apple ---
        apple_data = _safe_get_apple_summary(target_iso)
        if apple_data:
            dal.save_apple_daily(target_day, apple_data)
        else:
            failed_sources.append("Apple")

        # --- Wger ---
        day_logs = wger_data.get(target_iso, [])
        if day_logs:
            for i, log in enumerate(day_logs, start=1):
                dal.save_wger_log(
                    day=target_day,
                    exercise_id=log.get("exercise_id"),
                    set_number=i,
                    reps=log.get("reps"),
                    weight_kg=log.get("weight"),
                    rir=log.get("rir"),
                )
        else:
            failed_sources.append("Wger")

        # --- Body age (recalculated from source data) ---
        try:
            # Collect history window
            withings_history = []
            apple_history = []

            hist_data = dal.get_historical_data(
                start_date=target_day - timedelta(days=6),
                end_date=target_day,
            )
            for r in hist_data:
                withings_history.append({
                    "weight": r.get("weight_kg"),
                    "fat_percent": r.get("body_fat_pct"),
                })
                apple_history.append({
                    "steps": r.get("steps"),
                    "exercise_minutes": r.get("exercise_minutes"),
                    "calories_active": r.get("calories_active"),
                    "calories_resting": r.get("calories_resting"),
                    "stand_minutes": r.get("stand_minutes"),
                    "distance_m": r.get("distance_m"),
                    "hr_resting": r.get("hr_resting"),
                    "hr_avg": r.get("hr_avg"),
                    "hr_max": r.get("hr_max"),
                    "hr_min": r.get("hr_min"),
                    "sleep_total_minutes": r.get("sleep_total_minutes"),
                    "sleep_asleep_minutes": r.get("sleep_asleep_minutes"),
                    "sleep_rem_minutes": r.get("sleep_rem_minutes"),
                    "sleep_deep_minutes": r.get("sleep_deep_minutes"),
                    "sleep_core_minutes": r.get("sleep_core_minutes"),
                    "sleep_awake_minutes": r.get("sleep_awake_minutes"),
                })

            result = body_age.calculate_body_age(
                withings_history=withings_history,
                apple_history=apple_history,
                profile={"age": settings.USER_AGE},  # configurable
            )
            if result:
                result["date"] = target_day.isoformat()
                dal.save_body_age_daily(target_day, result)
            else:
                log_utils.log_message(
                    f"[sync] No body age result for {target_iso}", "WARN"
                )
        except Exception as e:
            log_utils.log_message(
                f"[sync] Body age calculation failed for {target_iso}: {e}", "ERROR"
            )
            failed_sources.append("BodyAge")

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
    dal = dal or PostgresDal()
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
    sys.exit(_main())
