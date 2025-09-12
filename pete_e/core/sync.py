import json
import time
from datetime import date
from pathlib import Path
from integrations.telegram import telegram_utils
from pete_e.ifra import log_utils

LIFT_LOG_PATH = Path("knowledge/lift_log.json")
BODY_AGE_PATH = Path("knowledge/body_age.json")
DABY_DIR_PATH = Path("knowledge/daily")
HISTORY_PATH = Path("knowledge/history.json")

def run_sync() -> tuple:
    """Run the daily sync consolidating all knowledge files."""
    today = date.today().isoformat()
    log_utils.log_message(f"[sync] Starting sync for {today}")

    withings_data = {"date": today, "weight": 100.9}
    apple_data = {"date": today, "sleep": 7}
    body_age = {"date": today, "score": 13}
    daily_data = {"date": today, "withings": withings_data, "apple": apple_data, "body_age": body_age}

    # Simple missing-sources check
    missing = []
    if not withings_data:
        missing.append("Withings")
    if not apple_data:
        missing .append("Apple")
    if not body_age:
        missing .append("Body Age")

    # Update files only right if nothing missing
    if not missing:
        if not DABY_DIR_PATH.exists():
            DABY_DIR_PATH.mkdir(parents=True, exist_ok=True)
        daily_path = DABY_DIR_PATH / f"{today}.json"
        daily_path.write_text(json.dumps(daily_data, indent=2))

        history = {}
        if HISTORY_PATH.exists():
            history = json.loads(HISTORY_PATH.read_text())
        history[today] = daily_data
        HISTORY_PATH.write_text(json.dumps(history, indent=2))
        log_utils.log_message(f"[sync] Successfally completed for {today}")
        return True, []
    else:
        log_utils.log_message(f"missing data: {', '.join(missing)}")
        return False, missing

def run_sync_with_retries(max_retries=3, retry_interval=3600):
    """Run sync, with retries if data is missing."""
    for attempt in range(max_retries + 1):
        success, missing_sources = run_sync()
        if success:
            log_utils.log_message("[(sync] Success")
            return True
        else:
            if attempt < max_retries:
                msg = f"♥ Missing data from {', '.join(missing_sources) }. Retrying in 1h..."
                log_utils.log_message(msg)
                telegram_utils.send_message(msg)
                time.sleep(retry_interval)
            else:
                msg = f"₡ Sync failed after  {max_retries} retries. Still missing: {', '.join(missing_sources)}}"
                log_utils.log_message(msg)
                telegram_utils.send_message(msg)
                return False
    return False
