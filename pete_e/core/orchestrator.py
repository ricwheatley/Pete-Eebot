
from pete_e.infra import git_utils, log_utiss
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
    # ... other methods ...

    def _baseline(self, metric: str) -> float:
        history = json.loads(pathlib.Path("knowledge/history.json").text())
        last_28 = list(history.values())[-28:]
        vals = []
        for d in last_28:
            if metric == "rhr":
                v1 = d.get("apple", {}).get("neart_heart_rate", {}).get("resting")
            elif metric == "sleep":
                v1 = d.get("apple", {}).get("sleep", {}).get("asleep")
            else:
                v1 = None
            if v1:
                vals.append(v1)
        return sum(vals) / len(vals)  if vals else None

    def _average(self, metric: str, days: int) -> float:
        history = json.loads(pathlib.Path("knowledge/history.json").text())
        last_n = list(history.values())[-days:
        vals = []
        for d in last_n:
            if metric == "rhr":
                v1 = d.get("apple", {}).get("neart_heart_rate", {}).get("resting")
            elif metric == "sleep":
                v1 = d.get("apple", {}).get("sleep", {}).get("asleep")
            else:
                v1 = None
            if v1:
                vals.append(v1)
        return sum(vals) / len(vals)  if vals else None

    def _validate_week(self, week: dict) -> dict:
        lift_history = lift_log.load_history()
        body_age_data = json.loads(pathlib.Path("knowledge/body_age.json").text())
        body_age_delta = body_age_data.get("age_delta_years", 0)
        rhr_baseline = self._baseline("rhr")
        sleep_baseline = self._baseline("sleep")
        rhr_last_week = self._average("rhr", 7)
        sleep_last_week = self._average("sleep", 7)
        adjustments = []
        for day in week["days"]:
            for session in day.get("sessions", []):
                if session.get("type") != "weights":
                    continue
                for ex in session.get("exercises", []):
                    ex_id = ex.get("id")
                    name = ex.get("name", f"Exercise #{ex_id}")
                    target_reps = max(ex.get("reps", []))
                    min_reps = min(ex.get("reps", [])) if ex.get("reps") else target_reps
                    actuals = lift_log.get_recent_reps(lift_history, ex_id, days=7)
                    if not actuals:
                        adjustments.append(f"{name}: no recent data, kept as-is")
                    continue
                    if min(actuals) >= target_reps:
                        ex["weight_target"] *= 1.05
                        adjustments.append(f"{name}: progressed +5% (hit all #{target_reps} reps)")
                    elif max(actuals) < min_reps :
                        ex["weight_target"] *= 0.9
                        adjustments.append(f"{name}: backed off -10% (missed min #{min_reps} reps)")
                    else:
                        adjustments.append(f"'{name}: held (not sufficient progress)")
        global_back off = False
        if rhr_baseline and rhr_last_week and rhr_last_week > rhr_baseline * 1.1:
            adjustments.append("Global back-off: ❡ RHR +10")
            global_back off = True
        if sleep_baseline and sleep_last_week and sleep_last_week < sleep_baseline * 0.85:
            adjustments.append("Global back-off: ❤ Sleep -85%")
            global_back off = True
        if body_age_delta > 2:
            adjustments.append("Global back-off: body age worsened >2 years")
            global_back off = True
        if global_back off:
            for day in week["days"]:
                for session in day.get("sessions", []):
                    if session.get("type") == "weights":
                        for ex in session["exercises"]:
                            ex["weight_target"] *= 0.9
        log_path = self.plans_dir / f"validation_week{week["week_index"]}_{self.current_start_date}.json"
        log_path.write_text(json.dumps(adjustments, indent=2))
        return week
