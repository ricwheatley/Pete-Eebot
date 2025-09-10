import argparse, os, json, pathlib, subprocess, random, pytz, re
from datetime import datetime, date, timedelta
from integrations.pete_feedback import narrative_builder as nb
from integrations.pete_feedback.phrase_picker import random_phrase
from integrations.pete_feedback.utils import stitch_sentences
from integrations.wger import plan_next_block, wger_uploads

METRICS_PATH = pathlib.Path("knowledge/history.json")
LOG_PATH = pathlib.Path("summaries/logs/pete_history.log")
PLANS_DIR = "integrations/wger/plans"

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
    subprocess.run([
        "git", "add", "summaries", "knowledge", "integrations/wger/logs", "docs/analytics", "integrations/wger/plans"
    ], check=False)

    msg = f"Pete log update ({report_type}) | {phrase} ({datetime.utcnow().strftime('%Y-%m-%d')})"
    try:
        subprocess.run(["git", "commit", "-m", msg], check=True)
        subprocess.run(["git", "push"], check=True)
    except subprocess.CalledProcessError:
        print("No changes to commit.")

# --- Cycle gating helpers ---
def get_last_cycle_start():
    files = [os.path.join(PLANS_DIR, f) for f in os.listdir(PLANS_DIR) if f.startswith("plan_") and f.endswith(".json")]
    if not files:
        return None
    latest_file = max(files, key=os.path.getctime)
    with open(latest_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    dates = [datetime.strptime(d["date"], "%Y-%m-%d").date() for d in data.get("days", []) if d.get("date")]
    return min(dates) if dates else None

def can_start_new_cycle(today=None):
    today = today or datetime.today().date()
    last_start = get_last_cycle_start()
    if not last_start:
        return True
    return today >= last_start + timedelta(days=28)

# --- Main ---
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", choices=["daily", "weekly", "cycle", "random"], required=True)
    parser.add_argument("--start-date", type=str, help="Force cycle start date (YYYY-MM-DD, ignores 28-day rule)")
    args = parser.parse_args()

    metrics = load_metrics()

    if args.type == "daily":
        msg = nb.build_daily_narrative(metrics)
        phrase = random_phrase(mode="serious")

    elif args.type == "weekly":
        msg = nb.build_weekly_narrative(metrics)
        phrase = random_phrase(kind="coachism")

    elif args.type == "cycle":
        if args.start_date:
            start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
            msg = f"⚡ Forced new cycle starting {start_date} (manual override)."
        else:
            if not can_start_new_cycle():
                msg = f"⏸ Still mid-cycle (last start {get_last_cycle_start()}). No new cycle created."
                send_telegram(msg)
                log_message(msg)
                return
            start_date = date.today()
            msg = f"✅ New cycle created | Start: {start_date}"

        # Build new 4-week cycle
        block = plan_next_block.build_block(start_date)

        # Save JSON plan
        plan_dir = pathlib.Path(PLANS_DIR)
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_path = plan_dir / f"plan_{start_date.isoformat()}.json"
        plan_path.write_text(json.dumps(block, indent=2), encoding="utf-8")

        # Convert to entries for WGER
        entries = []
        for day in block.get("days", []):
            for session in day.get("sessions", []):
                entries.append(session)

        payload = wger_uploads.load_and_normalize({"entries": entries})
        for session in payload:
            wger_uploads.create_session(session)

        phrase = random_phrase(mode="serious")

    elif args.type == "random":
        greetings = random.choice([
            "Ey up Ric 👊 got your new block sorted.",
            "Alright mate, fresh 4-week cycle coming in.",
            "New block time 🔥 here’s what’s on deck:"
        ])
        msg = greetings
        phrase = random_phrase(mode="chaotic")

    send_telegram(msg)
    log_message(msg)
    commit_changes(args.type, phrase)

if __name__ == "__main__":
    main()