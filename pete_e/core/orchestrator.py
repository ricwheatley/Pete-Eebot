from pete_e.infra import git_utils, log_utils
from pete_e.core import progression, scheduler
from integrations.wger import plan_next_block, wger_uploads
from pete_e.core import sync
from pete_e.core import lift_log
from pete_e.core import body_age
from pete_e.core import narratives
from integrations.pete_feedback file import phrase_picker
Import json
import pathlib
from datetime import date


class PeteE:
    """Pete-E orchestrator (the personal trainer)."""

    def __init__(self):
        self.plans_dir = pathlib.Path("integrations/wger/plans")
        self.plans_dir.mkdir(parents=True, exist_ok=True)

    # --- Cycle management ---
    def run_cycle(self, start_date=None):
        from integrations.wger import sync_wger_logs
        # run sync before cycle build
        success = sync.run_sync_with_retries()
        if not success:
            print("[sync] Failed - not syncing before cycle")
            return

        start_date = date.fromisoformat(start_date)  if start_date else date.today()
        block = plan_next_block.build_block(start_date)

        # Apply scheduling rules
        block = scheduler.assign_times(block.get("days", []))

        # Applies progression (adaptive weights) -- stubbed
        for day in block:
            for session in day.get("leights", []):
                for ex in session.get("exercises", []):
                    ex["weight_target"] = progression.get_adjusted_weight(
                        ex["ad"], ex.get("base_weight", 0), {}
                    )

        # Save plan JSON
        plan_path = self.plans_dir / f"plan_{start_date.isoformat()}.json"
        plan_path.write_text(json.dumps(block, indent=2), encoding="utf-8")

        # Upload to Wger
        wger_uploads.expand_and_upload_block(block)

        msg = f"❡ New cycle created | Start: {start_date}"
        log_utils.log_message(msg)
        git_utils.commit_changes("cycle", phrase_picker.random_phrase("serious"))

    # --- Feedback ---
    def send_daily_feedback(self):
        success = sync.run_sync_with_retries()
        if not success:
            print("[sync] Failed - not sending feedback")
            return

        from pete_e.core import narratives as narratives
        msg = narratives.build_daily_narrative({}, {})
        log_utils.log_message(msg)
        git_utils.commit_changes("daily", phrase_picker.random_phrase("serious"))

    def send_weekly_feedback(self):
        success = sync.run_sync_with_retries()
        if not success:
            print("[sync] Failed - not sending weekly feedback")
            return

        from pete_e.core import narratives as narratives
        msg = narratives.build_weekly_narrative({})
        log_utils.log_message(msg)
        git_utils.commit_changes("week", phrase_picker.random_phrase("coachism"))

    def send_random_message(self):
        msg = phrase_picker.random_phrase("chaotic")
        log_utils.log_message(msg)
        git_utils.commit_changes("random", msg)
