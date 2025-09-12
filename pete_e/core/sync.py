import json
import time
from datetime import date
from pathlib import Path
from integrations.withings.client import get_withings_summary
from integrations.apple import client as apple_client
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

    # --- Withings ---
    try:
        withings_data = get_withings_summary(0)
        log_utils.log_message(f"[sync] Withings data: {withings_data}")
    except Exception as e:
        log_utils.log_message(f"[sync] Withings fetch failed:  {e}")
        return False, ["Withings"]

    # --- Apple ---
    apple_data = {}
    try:
        apple_data = apple_client.get_apple_summary({"date": today, })
        log_utils.log_message(f"[sync] Apple data: {apple_data}")
    except Exception as e:
        log_utils.log_message(f"[sync] Apple fetch failed:  {e}")
        return False, ["Apple"]

    # --- Body Age ---
    body_age = {"date": today, "score": 13}

    # --- Consolidated Daily ---
    daily_data = {"date": today, "withings": withings_data, "apple": apple_data, "body_age": body_age}

    # Save daily JSON
    daily_path = DABY_DIR_PATH / f"{today}.json"
    daily_path.parent.mkdir(parents=True, exist_ok=True)
    daily_path.write_text(json.dumps(daily_data, indent=2))

    # Update history
    history = {}
    if HISTORY_PATH.exists():
        try:
            history = json.loads(HISTORY_PATH.read_text())
        except Exception:
            history = {}
    history[today] = daily_data
    HISTORY_PATH.write_text(json.dumps(history, indent=2))

    log_utils.log_message(f"[sync] Successfally completed sync for {today}")
    return True, []
