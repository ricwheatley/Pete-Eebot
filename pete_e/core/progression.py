"""Adaptive weight progression logic using the Data Access Layer."""

import statistics
from typing import Tuple

from pete_e.data_access.dal import DataAccessLayer
from pete_e.config import settings


def apply_progression(
    dal: DataAccessLayer, week: dict, lift_history: dict | None = None
) -> Tuple[dict, list[str]]:
    """
    Adjust weights per exercise based on recent actuals in lift log.

    Args:
        dal: Data access layer for retrieving lift history.
        week: Training week structure.
        lift_history: Cached lift_log data. If None, load via DAL.

    Returns:
        (adjusted_week, adjustment_logs)
    """
    if lift_history is None:
        lift_history = dal.load_lift_log()

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

                inc_factor = 1 + settings.PROGRESSION_INCREMENT
                dec_factor = 1 - settings.PROGRESSION_DECREMENT

                if avg >= base_weight:
                    ex["weight_target"] = round(base_weight * inc_factor, 2)
                    adjustments.append(
                        f"{name}: progressed +{settings.PROGRESSION_INCREMENT*100:.0f}% (avg {avg:.1f} ≥ base {base_weight:.1f})"
                    )
                elif avg < base_weight:
                    ex["weight_target"] = round(base_weight * dec_factor, 2)
                    adjustments.append(
                        f"{name}: backed off -{settings.PROGRESSION_DECREMENT*100:.0f}% (avg {avg:.1f} < base {base_weight:.1f})"
                    )
                else:
                    adjustments.append(f"{name}: held at {base_weight}kg")

    return week, adjustments
