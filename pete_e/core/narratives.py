"""
Narratives and reporting for Pete-E.
Handles daily, weekly, and random messaging, plus commits and logging.
"""

import os
import json
import pathlib
import subprocess
import random
from datetime import datetime
import requests

from pete_e.core import narratives as nb
from pete_e.core.phrase_picker import random_phrase
from pete_e.core.narrative_utils import stitch_sentences

# Paths
METRICS_PATH = pathlib.Path("knowledge/history.json")
LOG_PATH = pathlib.Path("summaries/logs/pete_history.log")


# --- Helpers ---
def load_metrics() -> dict:
    return json.loads(METRICS_PATH.read_text()) if METRICS_PATH.exists() else {}


def send_telegram(msg: str) -> None:
    """Send a message to Telegram using bot token + chat id."""
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID")
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": msg},
        timeout=20,
    )
    r.raise_for_status()


def log_message(msg: str) -> None:
    """Append timestamped log entry to Pete history log."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.utcnow().isoformat()}] {msg}\n")


def commit_changes(report_type: str, phrase: str) -> None:
    """Commit changes to git with a standardised message."""
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
    subprocess.run(
        ["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"],
        check=True,
    )
    subprocess.run(["git", "add", "-A"], check=False)

    msg = f"Pete log update ({report_type}) | {phrase} ({datetime.utcnow().strftime('%Y-%m-%d')})"
    try:
        subprocess.run(["git", "commit", "-m", msg], check=True)
        subprocess.run(["git", "push"], check=True)
    except subprocess.CalledProcessError:
        print("No changes to commit.")


# --- Entrypoint ---
def run_narrative(report_type: str) -> None:
    """
    Run a narrative flow for daily, weekly, or random messages.
    """
    metrics = load_metrics()

    if report_type == "daily":
        msg = nb.build_daily_narrative(metrics)
        phrase = random_phrase(mode="serious")

    elif report_type == "weekly":
        msg = nb.build_weekly_narrative(metrics)
        phrase = random_phrase(kind="coachism")

    elif report_type == "random":
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

    send_telegram(msg)
    log_message(msg)
    commit_changes(report_type, phrase)
