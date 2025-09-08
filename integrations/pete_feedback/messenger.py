# integrations/pete_feedback/messenger.py
import argparse, os, json, pathlib, subprocess, random
from datetime import datetime
from integrations.pete_feedback import narrative_builder as nb
from integrations.pete_feedback.catchphrases import random_phrase
from integrations.pete_feedback.utils import stitch_sentences

METRICS_PATH = pathlib.Path("docs/analytics/unified_metrics.json")
LOG_PATH = pathlib.Path("summaries/logs/pete_history.log")


def load_metrics():
    if METRICS_PATH.exists():
        return json.loads(METRICS_PATH.read_text())
    return {}


def send_telegram(msg: str):
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID")
    subprocess.run([
        "curl", "-s", "-X", "POST",
        f"https://api.telegram.org/bot{token}/sendMessage",
        "-d", f"chat_id={chat_id}",
        "-d", f"text={msg}"
    ], check=True)


def log_message(msg: str):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.utcnow().isoformat()}] {msg}\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", choices=["daily", "weekly", "cycle", "rant"], required=True)
    args = parser.parse_args()

    metrics = load_metrics()

    if args.type == "daily":
        msg = nb.build_daily_narrative(metrics)
    elif args.type == "weekly":
        msg = nb.build_weekly_narrative(metrics)
    elif args.type == "cycle":
        msg = nb.build_cycle_narrative(metrics)
    elif args.type == "rant":
        sprinkles = [random_phrase(mode="chaotic") for _ in range(random.randint(3, 6))]
        msg = "🔥 Random Pete Rant 🔥\n\n" + stitch_sentences([], sprinkles, short_mode=random.random() < 0.2)

    send_telegram(msg)
    log_message(msg)


if __name__ == "__main__":
    main()