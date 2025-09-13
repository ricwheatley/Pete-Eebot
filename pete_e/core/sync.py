import time
from datetime import date, timedelta

# Import centralized components
from pete_e.config import settings
from pete_e.infra import log_utils

# Import refactored clients, modules, and the DAL contract
from pete_e.core.withings_client import WithingsClient
from integrations.wger.client import WgerClient
from pete_e.core import apple_client, body_age, lift_log
from pete_e.data_access.dal import DataAccessLayer
from pete_e.data_access.json_dal import JsonDal
try:
    from pete_e.data_access.postgres_dal import PostgresDal
except Exception:  # pragma: no cover - optional
    PostgresDal = None


def _get_dal() -> DataAccessLayer:
    """Select the appropriate DAL based on environment settings."""
    if (
        PostgresDal
        and settings.DATABASE_URL
        and settings.ENVIRONMENT == "production"
    ):
        try:
            return PostgresDal()
        except Exception as e:  # pragma: no cover - fallback
            log_utils.log_message(
                f"Postgres DAL init failed: {e}. Falling back to JSON.", "WARN"
            )
    return JsonDal()


def run_sync(dal: DataAccessLayer) -> tuple[bool, list[str]]:
    """
    Run the daily sync, consolidating data from all sources and saving via the DAL.
    """
    today = date.today()
    today_iso = today.isoformat()
    log_utils.log_message(f"[sync] Starting sync for {today_iso}", "INFO")

    # Initialize clients
    withings_client = WithingsClient()
    wger_client = WgerClient()
    failed_sources = []
    withings_data = {}
    apple_data = {}
    wger_data = {}

    # --- Withings ---
    try:
        withings_data = withings_client.get_summary(target_date=today - timedelta(days=1))
        log_utils.log_message(f"[sync] Withings data fetched: {withings_data}", "INFO")
    except Exception as e:
        log_utils.log_message(f"[sync] Withings fetch failed: {e}", "ERROR")
        failed_sources.append("Withings")

    # --- Apple ---
    try:
        apple_data = apple_client.get_apple_summary({"date": today_iso})
        log_utils.log_message(f"[sync] Apple data fetched: {apple_data}", "INFO")
    except Exception as e:
        log_utils.log_message(f"[sync] Apple fetch failed: {e}", "ERROR")
        failed_sources.append("Apple")

    # Save Withings and Apple summaries so foreign key exists for strength logs
    dal.save_daily_summary({"withings": withings_data, "apple": apple_data}, today)

    # --- Wger Logs ---
    try:
        wger_data = wger_client.get_logs(days=1)
        log_utils.log_message(
            f"[sync] Wger logs fetched: {len(wger_data.get(today_iso, []))} entries",
            "INFO",
        )
        for d, logs_list in wger_data.items():
            for log in logs_list:
                lift_log.append_log_entry(
                    dal=dal,
                    exercise_id=log.get("exercise_id"),
                    weight=log.get("weight"),
                    reps=log.get("reps"),
                    sets=log.get("sets"),
                    rir=log.get("rir"),
                    log_date=d,
                )
    except Exception as e:
        log_utils.log_message(f"[sync] Wger fetch failed: {e}", "ERROR")
        failed_sources.append("Wger")

    if failed_sources:
        return False, failed_sources

    # --- Body Age ---
    try:
        body_age_result = body_age.calculate_body_age(
            [withings_data, apple_data], profile={"age": 40}
        )
        log_utils.log_message(f"[sync] Body Age calculated: {body_age_result}", "INFO")
    except Exception as e:
        log_utils.log_message(f"[sync] Body Age calculation failed: {e}", "ERROR")
        body_age_result = {}

    # --- Consolidated Daily ---
    daily_data = {
        "date": today_iso,
        "withings": withings_data,
        "apple": apple_data,
        "wger": wger_data.get(today_iso, []),
        "body_age": body_age_result,
    }

    log_utils.log_message(f"[sync] Successfully completed sync for {today_iso}", "INFO")
    return True, []


def run_sync_with_retries(
    dal: DataAccessLayer | None = None, retries: int = 3, delay: int = 60
) -> bool:
    """Attempt to run the sync multiple times if it fails, selecting DAL if needed."""
    dal = dal or _get_dal()
    for i in range(retries):
        success, failed = run_sync(dal=dal)
        if success:
            return True
        log_utils.log_message(
            f"[sync] Attempt {i + 1}/{retries} failed. Failed sources: {failed}. Retrying in {delay}s...",
            "WARN",
        )
        time.sleep(delay)
    log_utils.log_message(f"[sync] All {retries} sync attempts failed.", "ERROR")
    return False

