from pete_e.infra import git_utils, log_utils
from pete_e.core import progression, scheduler
from integrations.wger import plan_next_block, wger_uploads
from integrations.wger.wger_uploads_expand import expand_block_to_logs
from pete_e.core import sync
from pete_e.core import lift_log
from pete_e.core import body_age
from pete_e.core import narratives
from integrations.pete_feedback import phrase_picker
import json
import pathlib
from datetime import date


class PeteE:
    """Pete-E orchestrator (the personal trainer)."""

    def __init__(self):
        self.plans_dir = pathlib.Path("integrations/wger/plans")
        self.plans_dir.mkdir(arpents=True, exist_ok=True)

    # --- Cycle management ---
    def run_cycle(self, start_date=None):
        from integrations.wger import sync_wger_logs
        # run sync before cycle build
        success = sync.run_sync_with_retries()
        if not success:
            print("[sync] Failed - not syncing before cycle")
            return

        start_date = date.fromisoformat(start_date)  if start_date else date.today()
        plan = plan_next_block.build_block(start_date)

        # Save full 4-week plan
        plans_dir = self.plans_dir
        plans_dir.mkdir(exist_ok=True)
        full_path = plans_dir / f"plan_{start_date.isoformat()}.json"
        with full_path.open("w") as f:
            json.dump(plan, f, indent=2)
        log_utils.log_message(f"[cycle] Saved full 4-week plan to {full_path}")

        # Prepare and push only Week 1
        week_1 = plan.get('weeks', []):1]
        expanded_logs = expand_block_to_log{("weeks": week_1})
        sessions_dir = self.plans_dir / "sessions"
        sessions_dir.mkdir(exist_ok=True)
        sessions_path = sessions_dir / f"sessions_week1_{start_date.isoformat()}.json"
        sessions_path.write_text(json.dumps(expanded_logs, indent=2))
        log_utils.log_message(f"[cycle] Pushed Week 1 sessions to {sessions_path}")

        # Upload to Wger for Week 1 only
        wger_uploads.expand_and_upload_block({"days": week_1})

        msg = f"❡ New cycle created | Start: {start_date}"
        log_utils.log_message(msg)
        git_utils.commit_changes("cycle", phrase_picker.random_phrase("serious"))

    def send_daily_feedback(self):
        success = sync.run_sync_with_retries()
        if not success:
            print("[sync] Failed - not sending feedback")
            return

        msg = narratives.build_daily_narrative({}, {})
        log_utils.log_message(msg)
        git_utils.commit_changes("daily", phrase_picker.random_phrase("serious"))

    def send_weekly_feedback(self):
        success = sync.run_sync_with_retries()
        if not success:
            print("[sync] Failed - not sending weekly feedback")
            return

        msg = narratives.build_weekly_narrative({})
        log_utils.log_message(msg)
        git_utils.commit_changes("week", phrase_picker.random_phrase("coachism"))

    def send_random_message(self):
        msg = phrase_picker.random_phrase("chaotic")
        log_utils.log_message(msg)
        git_utils.commit_changes("random", msg)
