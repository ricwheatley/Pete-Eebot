"""Adaptive weight progression logic using lift_log repository."""

import statistics
from pete_e.core import lift_log
from typing import Tuple


def apply_progression(week: dict, lift_history: dict | None = None) -> Tuple[dict, list[str]]:
    """
    Adjust weights per exercise based on recent actuals in lift log.

    Args:
        week (dict): Training week structure.
        lift_history (dict | None): Cached lift_log data. If None, load fresh.

    Returns:
        (adjusted_week, adjustment_logs)
    """
    if lift_history is None:
        lift_history = lift_log.load_log()

    adjustments = []

    for day in week.get("days", []):
        for session in day.get("sessions", []):
            if session.get("type") != "weights":
                continue
            for ex in session.get("exercises", []):
                ex_id = str(ex.get("id"))
                name = ex.get("name", f"Exercise #{ex_id}")

                entries = lift_history.get(ex_id, [])
                if not entries:
                    adjustments.append(f"{name}: no history, kept at {ex.get('weight_target', 0)}kg")
                    continue

                # Look at the last 4 entries
                last_entries = entries[-4:]
                weights = [e.get("weight") for e in last_entries if e.get("weight")]

                if not weights:
                    adjustments.append(f"{name}: no valid weight data, kept at {ex.get('weight_target', 0)}kg")
                    continue

                avg = statistics.mean(weights)
                base_weight = ex.get("weight_target", weights[-1])

                if avg >= base_weight:
                    ex["weight_target"] = round(base_weight * 1.05, 2)
                    adjustments.append(f"{name}: progressed +5% (avg {avg:.1f} ≥ base {base_weight:.1f})")
                elif avg < base_weight:
                    ex["weight_target"] = round(base_weight * 0.95, 2)
                    adjustments.append(f"{name}: backed off -5% (avg {avg:.1f} < base {base_weight:.1f})")
                else:
                    adjustments.append(f"{name}: held at {base_weight}kg")

    return week, adjustments
