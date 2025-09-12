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
    ...

    def validate_and_push_next_week(self, week_index: int):
        """Validate week actual logs vs targets, adjust if needed, and push to Wger."""
        success = sync.run_sync_with_retries()
        if not success:
            log_utils.log_message(f"[cycle] Validation failed - no sync data")
            return

        plan_path = self.plans_dir / f"plan_{self.current_start_date}.json"
        if not plan_path.exists():
            log_utils.log_message(f"[cycle] No plan file found: {plan_path}")
            return
        plan = json.loads(plan_path.read_text())

        week = next((w for w in plan["weeks"] if w["week_index"] == week_index), None)
        if not week:
            log_utils.log_message(f"[cycle] No week {week_index} found in plan")
            return
        
        # Placeholder for validation logic
        adjusted_week = self._validate_week(week)
        
        # Expand and push the week
        expanded_logs = expand_block_to_logs({"weeks": [adjusted_week]})
        week_path = self.plans_dir / f"week_{week_index}_{self.current_start_date}.json"
        week_path.write_text(json.dumps(expanded_logs, indent=2))
        wger_uploads.expand_and_upload_block({"days": adjusted_week["days"]})

        log_utils.log_message(f"[cycle] Week {week_index} validated and pushed")
        
    def _validate_week(self, week: dict) -> dict:
        """Placeholder for validation logic that checks actuals vs targets, recovery, etc."""
        # TODO: use lift_log and body_age to adjust load before pushing
        return week
