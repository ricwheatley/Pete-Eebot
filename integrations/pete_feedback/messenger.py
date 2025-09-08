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


def commit_changes(report_type: str, phrase: str):
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
    subprocess.run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"], check=True)

    # Add known directories
    subprocess.run(["git", "add", "summaries", "knowledge", "integrations/wger/logs", "docs/analytics"], check=False)

    msg = f"Pete log update ({report_type}) | {phrase} ({datetime.utcnow().strftime('%Y-%m-%d')})"
    try:
        subprocess.run(["git", "commit", "-m", msg], check=True)
        subprocess.run(["git", "push"], check=True)
    except subprocess.CalledProcessError:
        print("No changes to commit.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", choices=["daily", "weekly", "cycle", "rant"], required=True)
    args = parser.parse_args()

    metrics = load_metrics()

    # Build message
    if args.type == "daily":
        msg = nb.build_daily_narrative(metrics)
        phrase = random_phrase(mode="serious")
    elif args.type == "weekly":
        msg = nb.build_weekly_narrative(metrics)
        phrase = random_phrase(kind="coachism")
    elif args.type == "cycle":
        msg = nb.build_cycle_narrative(metrics)
        phrase = random_phrase(kind="metaphor", mode="chaotic")
    elif args.type == "rant":
        sprinkles = [random_phrase(mode="chaotic") for _ in range(random.randint(3, 6))]
        msg = "🔥 Random Pete Rant 🔥\n\n" + stitch_sentences([], sprinkles, short_mode=random.random() < 0.2)
        phrase = random_phrase(mode="chaotic")

    # Send + log + commit
    send_telegram(msg)
    log_message(msg)
    commit_changes(args.type, phrase)


if __name__ == "__main__":
    main()