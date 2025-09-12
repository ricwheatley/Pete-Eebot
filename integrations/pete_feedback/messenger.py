import argparse, os, json, pathlib, subprocess, random
from datetime import datetime, date, timedelta
import requests
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
    return json.loads(METRICS_PATH.read_text()) if METRICS_PATH.exists() else {}


def send_telegram(msg: str):
    token   = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID")
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": msg},
        timeout=20,
    )
    r.raise_for_status()


def log_message(msg: str):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.utcnow().isoformat()}] {msg}\n")


def commit_changes(report_type: str, phrase: str):
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
    subprocess.run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"], check=True)
    
    # Stage everything (fix for untracked files)
    subprocess.run(["git", "add", "-A"], check=False)
    
    msg = f"Pete log update ({report_type}) | {phrase} ({datetime.utcnow().strftime('%Y-%m-%d')})"
    try:
        subprocess.run(["git", "commit", "-m", msg], check=True)
        subprocess.run(["git", "push"], check=True)
    except subprocess.CalledProcessError:
        print("No changes to commit.")


def get_last_cycle_start():
    files = [os.path.join(PLANS_DIR, f) for f in os.listdir(PLANS_DIR) if f.startswith("plan_") and f.endswith(".json")]
    if not files:
        return None
    latest = max(files, key=os.path.getctime)
    with open(latest, "r", encoding="utf-8") as f:
        data = json.load(f)
    dates = [datetime.strptime(d["date"], "%Y-%m-%d").date() for d in data.get("days", []) if d.get("date")]
    return min(dates) if dates else None


def can_start_new_cycle(today=None):
    today = today or datetime.today().date()
    last = get_last_cycle_start()
    return True if not last else today >= last + timedelta(days=28)


# --- Main ---
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", choices=["daily", "weekly", "cycle", "random"], required=True)
    parser.add_argument("--start-date", type=str)
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
            msg = f"🔁 Forced new cycle starting {start_date} (manual override)."
        else:
            if not can_start_new_cycle():
                msg = f"⏳ Still mid-cycle (last start {get_last_cycle_start()}). No new cycle created."
                send_telegram(msg)
                log_message(msg)
                return
            start_date = date.today()
            msg = f"📅 New cycle created | Start: {start_date}"
        # Build block and send to wger
        block = plan_next_block.build_block(start_date)
        plan_dir = pathlib.Path(PLANS_DIR)
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_path = plan_dir / f"plan_{start_date.isoformat()}.json"
        plan_path.write_text(json.dumps(block, indent=2), encoding="utf-8")

        entries = [session for day in block.get("days", []) for session in day.get("sessions", [])]
        print(f"[DEBUG] Entries extracted: {len(entries)}")
        print(json.dumps(entries, indent=2))

        payload = wger_uploads.load_and_normalize({"entries": entries})
        print(f"[DEBUG] Normalized payload: {len(payload)} sessions")

        for session in payload:
            print(f"[DEBUG] Uploading session on {session.get('date')} (duration={session.get('duration')}, feeling={session.get('feeling')})")
            wger_uploads.create_session(session)

        phrase = random_phrase(mode="serious")

    elif args.type == "random":
        greetings = random.choice([
            "Ey up Ric 👋 got your new block sorted.",
            "Alright mate, fresh 4-week cycle coming in.",
            "New block time 🔄 here’s what’s on deck:",
        ])
        msg = greetings
        phrase = random_phrase(mode="chaotic")

    send_telegram(msg)
    log_message(msg)
    commit_changes(args.type, phrase)


if __name__ == "__main__":
    main()