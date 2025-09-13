"""
Narratives and reporting for Pete-E.
Handles daily, weekly, and random messaging, plus commits and logging.
"""

import json
import subprocess
import random
from datetime import datetime
import requests

# Import centralized components
from pete_e.config import settings
from pete_e.infra.log_utils import log_message

# Import local components for narrative building
from pete_e.core import narrative_builders as nb
from pete_e.core.phrase_picker import random_phrase

# Hardcoded paths and local log_message function have been removed.

# --- Helpers ---
def load_metrics() -> dict:
    """Load the historical metrics from the knowledge/history.json file."""
    history_path = settings.HISTORY_PATH
    if not history_path.exists():
        log_message("History file not found, returning empty metrics.", "WARN")
        return {}
    return json.loads(history_path.read_text(encoding="utf-8"))


def send_telegram(msg: str) -> None:
    """Send a message to Telegram using bot token + chat id from settings."""
    token = settings.TELEGRAM_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID
    
    if not token or not chat_id:
        log_message("TELEGRAM_TOKEN or TELEGRAM_CHAT_ID not set. Skipping message.", "WARN")
        return
        
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
            timeout=20,
        )
        r.raise_for_status()
        log_message("Telegram message sent successfully.")
    except requests.RequestException as e:
        log_message(f"Failed to send Telegram message: {e}", "ERROR")


def commit_changes(report_type: str, phrase: str) -> None:
    """Commit changes to git with a standardised message."""
    log_message("Attempting to commit changes to the repository.")
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
    subprocess.run(
        ["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"],
        check=True,
    )
    subprocess.run(["git", "add", "-A"], check=False)

    msg = f"Pete log update ({report_type}) | {phrase} ({datetime.utcnow().strftime('%Y-%m-%d')})"
    try:
        # Using --quiet to reduce log noise
        subprocess.run(["git", "commit", "-m", msg], check=True, capture_output=True)
        subprocess.run(["git", "push"], check=True, capture_output=True)
        log_message(f"Committed and pushed changes with message: {msg}")
    except subprocess.CalledProcessError as e:
        # This often means there were no changes to commit, which is not an error.
        log_message("No changes to commit or push.")


# --- Entrypoint ---
def run_narrative(report_type: str) -> None:
    """
    Run a narrative flow for daily, weekly, or random messages.
    """
    log_message(f"Running '{report_type}' narrative.")
    metrics = load_metrics()
    msg = ""
    phrase = ""

    if report_type == "daily":
        msg = nb.build_daily_narrative(metrics)
        phrase = random_phrase(mode="serious")

    elif report_type == "weekly":
        msg = nb.build_weekly_narrative(metrics)
        phrase = random_phrase(kind="coachism")

    elif report_type == "random":
        # Note: This logic seems incomplete based on the audit.
        # It sends a greeting but doesn't include the generated block.
        greetings = random.choice(
            [
                "Ey up Ric 👋 got your new block sorted.",
                "Alright mate, fresh 4-week cycle coming in.",
                "New block time 🔄 here’s what’s on deck:",
            ]
        )
        msg = greetings
        phrase = random_phrase(mode="chaotic")

    else:
        raise ValueError(f"Unknown report_type: {report_type}")

    if msg:
        send_telegram(msg)
        log_message(f"Generated message: {msg}")
        commit_changes(report_type, phrase)
    else:
        log_message(f"No message generated for '{report_type}' narrative. Skipping send and commit.", "WARN")
