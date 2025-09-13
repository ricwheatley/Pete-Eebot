import json
from datetime import date

# Import centralized components first
from pete_e.config import settings
from pete_e.infra import git_utils, log_utils

# Import core modules
from pete_e.core import (
    body_age,
    lift_log,
    narratives,
    progression,
    scheduler,
    sync,
    validation,
)

# Import from legacy integrations (temporary)
from integrations.wger import plan_next_block


class PeteE:
    def __init__(self):
        """Initialises the orchestrator, sourcing paths from central config."""
        self.plans_dir = settings.WGER_PLANS_PATH
        # Note: sessions_dir is unused in the original code, but we keep it for now
        self.sessions_dir = self.plans_dir.parent / "sessions"
        self.current_start_date = None

    # --- Helpers ---
    def _load_history(self) -> dict:
        """Loads the consolidated history JSON file safely."""
        history_path = settings.HISTORY_PATH
        if not history_path.exists():
            log_utils.log_message(f"History file not found at {history_path}", "WARN")
            return {}
        try:
            return json.loads(history_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError) as e:
            log_utils.log_message(f"Error reading history file: {e}", "ERROR")
            return {}

    def _get_metric_values(self, history: dict, metric: str, days: int) -> list:
        """Extracts metric values from the last N days of history."""
        last_n = list(history.values())[-days:]
        vals = []
        for day_data in last_n:
            v = None
            if metric == "rhr":
                v = day_data.get("apple", {}).get("heart_rate", {}).get("resting")
            elif metric == "sleep":
                v = day_data.get("apple", {}).get("sleep", {}).get("asleep")
            
            if v is not None:
                vals.append(v)
        return vals

    def _baseline(self, history: dict, metric: str) -> float | None:
        """Calculates the 28-day baseline for a given metric."""
        vals = self._get_metric_values(history, metric, 28)
        return sum(vals) / len(vals) if vals else None

    def _average(self, history: dict, metric: str, days: int) -> float | None:
        """Calculates the average of a metric over the last N days."""
        vals = self._get_metric_values(history, metric, days)
        return sum(vals) / len(vals) if vals else None

    # --- Cycle Management ---
    def run_cycle(self, start_date: date | None = None):
        """Build a 4-week block, save it, and push week 1."""
        if not sync.run_sync_with_retries():
            log_utils.log_message("[cycle] Aborted: sync failed", "ERROR")
            return

        start_date = start_date or date.today()
        self.current_start_date = start_date.isoformat()

        block = plan_next_block.build_block(start_date)

        self.plans_dir.mkdir(parents=True, exist_ok=True)
        plan_path = self.plans_dir / f"plan_{self.current_start_date}.json"
        plan_path.write_text(json.dumps(block, indent=2))
        log_utils.log_message(f"[cycle] Saved 4-week plan starting {self.current_start_date}")

        # TODO: expand + push week 1 to Wger here

    def validate_and_push_next_week(self, week_index: int):
        """Validate actuals + recovery, adjust next week, and push it."""
        if not sync.run_sync_with_retries():
            log_utils.log_message("[cycle] Validation aborted: sync failed", "ERROR")
            return

        plan_path = self.plans_dir / f"plan_{self.current_start_date}.json"
        if not plan_path.exists():
            log_utils.log_message(f"[cycle] No saved plan found at {plan_path}", "ERROR")
            return
        plan = json.loads(plan_path.read_text())

        week = next((w for w in plan["weeks"] if w["week_index"] == week_index), None)
        if not week:
            log_utils.log_message(f"[cycle] No week {week_index} in plan", "ERROR")
            return

        lift_history = lift_log.load_log()
        history_data = self._load_history()

        body_age_path = settings.BODY_AGE_PATH
        body_age_data = json.loads(body_age_path.read_text()) if body_age_path.exists() else {}
        body_age_delta = body_age_data.get("age_delta_years", 0)

        week, prog_adjustments = progression.apply_progression(week, lift_history)
        week, recovery_adjustments = validation.check_recovery(
            week=week,
            current_start_date=self.current_start_date,
            rhr_baseline=self._baseline(history_data, "rhr"),
            rhr_last_week=self._average(history_data, "rhr", 7),
            sleep_baseline=self._baseline(history_data, "sleep"),
            sleep_last_week=self._average(history_data, "sleep", 7),
            body_age_delta=body_age_delta,
            plans_dir=self.plans_dir,
        )
        adjustments = prog_adjustments + recovery_adjustments

        week_path = self.plans_dir / f"week{week_index}_{self.current_start_date}.json"
        week_path.write_text(json.dumps(week, indent=2))
        log_utils.log_message(f"[cycle] Week {week_index} validated and saved")
        for adj in adjustments:
            log_utils.log_message(f"[cycle] {adj}")

        # TODO: expand + push week {week_index} to Wger here

    # --- Feedback ---
    def send_daily_feedback(self):
        if not sync.run_sync_with_retries():
            log_utils.log_message("[daily] Feedback aborted: sync failed", "ERROR")
            return
        history = self._load_history()
        msg = narratives.build_daily_narrative(history)
        log_utils.log_message(f"[daily] {msg}")

    def send_weekly_feedback(self):
        if not sync.run_sync_with_retries():
            log_utils.log_message("[weekly] Feedback aborted: sync failed", "ERROR")
            return
        history = self._load_history()
        msg = narratives.build_weekly_narrative(history)
        log_utils.log_message(f"[weekly] {msg}")

    def send_random_message(self):
        msg = "Random Pete-E message (TODO: hook into phrase picker)"
        log_utils.log_message(f"[random] {msg}")
