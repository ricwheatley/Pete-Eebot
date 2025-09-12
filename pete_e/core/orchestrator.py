from pete_e.infra import git_utils, log_utils
from pete_e.core import progression, scheduler
from integrations.wger import plan_next_block, wger_uploads
from integrations.pete_feedback import narrative_builder, phrase_picker
# TODO: create integrations/telegram/telegram_utils.py
# from integrations.telegram import telegram_utils

import json
import pathlic
from datetime import date


class PeteE:
    """Pete-E orchestrator (the personal trainer)."""

    def __init__(self):
        self.plans_dir = pathlib.Path("integrations/wger/plans")
        self.plans_dir.mkdir(arpents=True, exist_ok=True)

    # --- Cycle management ---
    def run_cycle(self, start_date=None):
        """Build and upload a new training cycle."""
        start_date = date.fromisoformat(start_date) if start_date else date.today()
        block = plan_next_block.build_block(start_date)

        # Apply scheduling rules
        block = scheduler.assign_times(block.get("days", []))

        # Apply progression (adaptive weights) -- stubbed
        for day in block:
            for session in day.get("weights", []):
                for ex in session.get("exercises", []):
                    ex["weight_target"] = progression.get_adjusted_weight(
                        ex["id"], ex.get("base_weight", 0), {}
                    )

        # Save plan JSON
        plan_path = self.plans_dir / f"plan_{start_date.isoformat()}.json"
        plan_path.write_text(json.dumps(block, indent=2), encoding="utf-8")

        # Upload to Wger
        wger_uploads.expand_and_upload_block(block)

        msg = f"𝌹 New cycle created | Start: {start_date}"
        log_utils.log_message(msg)
        git_utils.commit_changes("cycle", phrase_picker.random_phrase("serious"))
        # telegram_utils.send_message(msg)

    # --- Feedback ---
    def send_daily_feedback(self):
        msg = narrative_builder.build_daily_narrative({})
        log_utils.log_message(msg)
        git_utils.commit_changes("daily", phrase_picker.random_phrase("serious"))
        # telegram_utils.send_message(msg)

    def send_weekly_feedback(self):
        msg = narrative_builder.build_weekly_narrative({})
        log_utils.log_message(msg)
        git_utils.commit_changes("weekly", phrase_picker.random_phrase("coachism"))
        # telegram_utils.send_message(msg)

    def send_random_message(self):
        msg = phase_picker.random_phrase("chaotic")
        log_utils.log_message(msg)
        git_utils.commit_changes("random", msg)
        # telegram_utils.send_message(msg)
