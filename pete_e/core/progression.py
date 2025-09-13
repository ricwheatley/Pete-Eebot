"""Adaptive weight progression logic using the Data Access Layer."""

from statistics import mean
from typing import Tuple

from pete_e.data_access.dal import DataAccessLayer
from pete_e.config import settings


def _average(values: list[float]) -> float:
    """Return the mean of a list, or 0 if empty."""

    return mean(values) if values else 0.0


def apply_progression(
    dal: DataAccessLayer, week: dict, lift_history: dict | None = None
) -> Tuple[dict, list[str]]:
    """Adjust weights based on lift log and recovery metrics."""

    if lift_history is None:
        lift_history = dal.load_lift_log()

    recent_metrics = dal.get_historical_metrics(7)
    baseline_metrics = dal.get_historical_metrics(settings.BASELINE_DAYS)

    rhr_7 = _average(
        [m.get("apple", {}).get("heart_rate", {}).get("resting") for m in recent_metrics if m.get("apple", {}).get("heart_rate", {}).get("resting") is not None]
    )
    sleep_7 = _average(
        [m.get("apple", {}).get("sleep", {}).get("asleep") for m in recent_metrics if m.get("apple", {}).get("sleep", {}).get("asleep") is not None]
    )
    rhr_baseline = _average(
        [m.get("apple", {}).get("heart_rate", {}).get("resting") for m in baseline_metrics if m.get("apple", {}).get("heart_rate", {}).get("resting") is not None]
    )
    sleep_baseline = _average(
        [m.get("apple", {}).get("sleep", {}).get("asleep") for m in baseline_metrics if m.get("apple", {}).get("sleep", {}).get("asleep") is not None]
    )

    recovery_good = True
    if rhr_baseline and sleep_baseline:
        if rhr_7 > rhr_baseline * (1 + settings.RHR_ALLOWED_INCREASE) or sleep_7 < sleep_baseline * settings.SLEEP_ALLOWED_DECREASE:
            recovery_good = False

    adjustments: list[str] = []

    for day in week.get("days", []):
        for session in day.get("sessions", []):
            if session.get("type") != "weights":
                continue
            for ex in session.get("exercises", []):
                ex_id = str(ex.get("id"))
                name = ex.get("name", f"Exercise #{ex_id}")

                entries = lift_history.get(ex_id, [])
                if not entries:
                    adjustments.append(
                        f"{name}: no history, kept at {ex.get('weight_target', 0)}kg"
                    )
                    continue

                last_entries = entries[-4:]
                weights = [e.get("weight") for e in last_entries if e.get("weight") is not None]
                rirs = [e.get("rir") for e in last_entries if e.get("rir") is not None]

                if not weights:
                    adjustments.append(
                        f"{name}: no valid weight data, kept at {ex.get('weight_target', 0)}kg"
                    )
                    continue

                avg_weight = mean(weights)
                use_rir = bool(rirs)
                avg_rir = mean(rirs) if use_rir else None

                target = ex.get("weight_target", avg_weight)
                inc = settings.PROGRESSION_INCREMENT
                dec = settings.PROGRESSION_DECREMENT

                if use_rir:
                    if avg_rir <= 1:
                        inc += settings.PROGRESSION_INCREMENT / 2
                    elif avg_rir >= 2:
                        inc /= 2

                if not recovery_good:
                    inc /= 2
                    dec *= 1.5

                detail = (
                    f"avg RIR {avg_rir:.1f}" if use_rir else "no RIR"
                ) + f", recovery {'good' if recovery_good else 'poor'}"

                if avg_weight >= target and (not use_rir or avg_rir <= 2):
                    ex["weight_target"] = round(target * (1 + inc), 2)
                    adjustments.append(
                        f"{name}: +{inc*100:.1f}% ({detail})"
                    )
                elif avg_weight < target or (use_rir and avg_rir > 2):
                    ex["weight_target"] = round(target * (1 - dec), 2)
                    adjustments.append(
                        f"{name}: -{dec*100:.1f}% ({detail})"
                    )
                else:
                    adjustments.append(
                        f"{name}: no change ({detail})"
                    )

    return week, adjustments
