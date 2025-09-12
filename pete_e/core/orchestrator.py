from pete_e.infra import git_utils, log_utils
from pete_e.core import progression, scheduler, sync, lift_log, body_age, narratives, validation
from integrations.wger import plan_next_block
import json
import pathlib
from datetime import date


class PeteE:
    def __init__(self):
        self.plans_dir = pathlib.Path("knowledge/wger/plans")
        self.sessions_dir = pathlib.Path("knowledge/wger/sessions")
        self.current_start_date = None

    # --- Helpers ---
    def _baseline(self, metric: str) -> float:
        """28-day baseline for a given metric (RHR, sleep)."""
        history = json.loads(pathlib.Path("knowledge/history.json").read_text())
        last_28 = list(history.values())[-28:]
        vals = []
        for d in last_28:
            if metric == "rhr":
                v = d.get("apple", {}).get("heart_rate", {}).get("resting")
            elif metric == "sleep":
                v = d.get("apple", {}).get("sleep", {}).get("asleep")
            else:
                v = None
            if v:
                vals.append(v)
        return sum(vals) / len(vals) if vals else None

    def _average(self, metric: str, days: int) -> float:
        """Average value of metric over the last N days."""
        history = json.loads(pathlib.Path("knowledge/history.json").read_text())
        last_n = list(history.values())[-days:]
        vals = []
        for d in last_n:
            if metric == "rhr":
                v = d.get("apple", {}).get("heart_rate", {}).get("resting")
            elif metric == "sleep":
                v = d.get("apple", {}).get("sleep", {}).get("asleep")
            else:
                v = None
            if v:
                vals.append(v)
        return sum(vals) / len(vals) if vals else None

    # --- Cycle Management ---
    def run_cycle(self, start_date: date | None = None):
        """Build a 4-week block, save it, and push week 1."""
        success = sync.run_sync_with_retries()
        if not success:
            log_utils.log_message("[cycle] Aborted: sync failed")
            return

        start_date = start_date or date.today()
        self.current_start_date = start_date.isoformat()

        # Build 4-week block
        block = plan_next_block.build_block(start_date)

        # Save full plan
        self.plans_dir.mkdir(parents=True, exist_ok=True)
        plan_path = self.plans_dir / f"plan_{self.current_start_date}.json"
        plan_path.write_text(json.dumps(block, indent=2))

        log_utils.log_message(f"[cycle] Saved 4-week plan starting {self.current_start_date}")

        # TODO: expand + push week 1 to Wger here

    def validate_and_push_next_week(self, week_index: int):
        """Validate actuals + recovery, adjust next week, and push it."""
        success = sync.run_sync_with_retries()
        if not success:
            log_utils.log_message("[cycle] Validation aborted: sync failed")
            return

        # Load full cycle plan
        plan_path = self.plans_dir / f"plan_{self.current_start_date}.json"
        if not plan_path.exists():
            log_utils.log_message("[cycle] No saved plan found")
            return

        plan = json.loads(plan_path.read_text())
        week = next((w for w in plan["weeks"] if w["week_index"] == week_index), None)
        if not week:
            log_utils.log_message(f"[cycle] No week {week_index} in plan")
            return

        lift_history = lift_log.load_log()
        body_age_data = json.loads(pathlib.Path("knowledge/body_age.json").read_text())
        body_age_delta = body_age_data.get("age_delta_years", 0)

        # 1. Apply per-exercise progression
        week, prog_adjustments = progression.apply_progression(week, lift_history)

        # 2. Apply recovery checks
        week, recovery_adjustments = validation.check_recovery(
            week=week,
            current_start_date=self.current_start_date,
            rhr_baseline=self._baseline("rhr"),
            rhr_last_week=self._average("rhr", 7),
            sleep_baseline=self._baseline("sleep"),
            sleep_last_week=self._average("sleep", 7),
            body_age_delta=body_age_delta,
            plans_dir=self.plans_dir,
        )

        adjustments = prog_adjustments + recovery_adjustments

        # Save validated week
        week_path = self.plans_dir / f"week{week_index}_{self.current_start_date}.json"
        week_path.write_text(json.dumps(week, indent=2))

        log_utils.log_message(f"[cycle] Week {week_index} validated and saved")
        for adj in adjustments:
            log_utils.log_message(f"[cycle] {adj}")

        # TODO: expand + push week {week_index} to Wger here

    # --- Feedback ---
    def send_daily_feedback(self):
        success = sync.run_sync_with_retries()
        if not success:
            log_utils.log_message("[daily] Feedback aborted: sync failed")
            return
        msg = narratives.build_daily_narrative(json.loads(pathlib.Path("knowledge/history.json").read_text()))
        log_utils.log_message(f"[daily] {msg}")

    def send_weekly_feedback(self):
        success = sync.run_sync_with_retries()
        if not success:
            log_utils.log_message("[weekly] Feedback aborted: sync failed")
            return
        msg = narratives.build_weekly_narrative(json.loads(pathlib.Path("knowledge/history.json").read_text()))
        log_utils.log_message(f"[weekly] {msg}")

    def send_random_message(self):
        msg = "Random Pete-E message (TODO: hook into phrase picker)"
        log_utils.log_message(f"[random] {msg}")
