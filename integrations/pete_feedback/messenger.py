import argparse, os, json, pathlib, subprocess, random, pytz
from datetime import datetime, date, timedelta
from integrations.pete_feedback import narrative_builder as nb
from integrations.pete_feedback.phrase_picker import random_phrase
from integrations.pete_feedback.utils import stitch_sentences
from integrations.wger import plan_next_block, wger_uploads

METRICS_PATH = pathlib.Path("knowledge/history.json")
LOG_PATH = pathlib.Path("summaries/logs/pete_history.log")

WEEK_INTENSITY = {
    1: {"name": "light"},
    2: {"name": "medium"},
    3: {"name": "heavy"},
    4: {"name": "deload"},
}


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

    subprocess.run(["git", "add", "summaries", "knowledge", "integrations/wger/logs", "docs/analytics", "integrations/wger/plans"], check=False)

    msg = f"Pete log update ({report_type}) | {phrase} ({datetime.utcnow().strftime('%Y-%m-%d')})"
    try:
        subprocess.run(["git", "commit", "-m", msg], check=True)
        subprocess.run(["git", "push"], check=True)
    except subprocess.CalledProcessError:
        print("No changes to commit.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", choices=["daily", "weekly", "cycle", "random"], required=True)
    args = parser.parse_args()

    metrics = load_metrics()

    if args.type == "daily":
        msg = nb.build_daily_narrative(metrics)
        phrase = random_phrase(mode="serious")

    elif args.type == "weekly":
        msg = nb.build_weekly_narrative(metrics)
        phrase = random_phrase(kind="coachism")

    elif args.type == "cycle":
        # 1. Build next 4-week block
        start_date = date.today()
        block = plan_next_block.build_block(start_date)

        # 2. Save JSON plan
        plan_dir = pathlib.Path("integrations/wger/plans")
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_path = plan_dir / f"plan_{start_date.isoformat()}.json"
        plan_path.write_text(json.dumps(block, indent=2), encoding="utf-8")

        # 3. Upload to WGER
        payload = wger_uploads.load_and_normalize(str(plan_path))
        for session in payload:
            wger_uploads.create_session(session)

        # 4. Friendly summary for Telegram
        week1 = [d for d in block["days"] if d["week"] == 1]
        summary_lines = []
        for day in week1:
            weights = next((s for s in day["sessions"] if s["type"] == "weights"), None)
            if weights:
                main = weights["exercises"][0]
                summary_lines.append(
                    f"{day['day']}: {main['name']} {main['sets']}×{main['reps']} ({main['intensity']})"
                )

        greeting = random.choice([
            "Ey up Ric 👋 got your new block sorted.",
            "Alright mate, fresh 4-week cycle coming in.",
            "New block time 💪 here’s what’s on deck:"
        ])

        msg = f"{greeting}\n\n"
        msg += f"Start date: {start_date}\n"
        msg += f"Cycle: {WEEK_INTENSITY[1]['name']} → {WEEK_INTENSITY[4]['name']}\n\n"
        msg += "Week 1 main lifts:\n" + "\n".join(summary_lines)
        msg += "\n\nBlaze classes are in as usual 🔥"

        phrase = random_phrase(mode="serious")

    elif args.type == "random":
        # Cheeky casual messages for a laugh or motivation
        greeting = random.choice([
            "Ey up Ric 👋",
            "Alright mate, here’s one for you:",
            "Oi Ric, check this:",
            "",  # sometimes no greeting at all
        ])

        sprinkles = [random_phrase(mode="chaotic") for _ in range(random.randint(1, 3))]
        msg = (greeting + "\n\n" if greeting else "") + stitch_sentences([], sprinkles, short_mode=True)

        phrase = random.choice(sprinkles)

    send_telegram(msg)
    log_message(msg)
    commit_changes(args.type, phrase)


if __name__ == "__main__":
    main()