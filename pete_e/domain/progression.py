"""Adaptive weight progression logic using the Data Access Layer."""

from dataclasses import dataclass

from statistics import mean
from typing import Any, Dict, List, Tuple

from pete_e.domain.data_access import DataAccessLayer
from pete_e.config import settings
from pete_e.infrastructure import log_utils
from pete_e.utils import converters, math as math_utils


def _collect_lift_history(
    dal: DataAccessLayer, week: dict, lift_history: dict | None
) -> dict:
    """Load lift history for all exercises in the provided week."""

    if lift_history is not None:
        return lift_history

    requested_ids: set[int] = set()
    for day in week.get("days", []):
        for session in day.get("sessions", []):
            if session.get("type") != "weights":
                continue
            for ex in session.get("exercises", []):
                ex_id = ex.get("id")
                if ex_id is None:
                    continue
                try:
                    requested_ids.add(int(ex_id))
                except (TypeError, ValueError):
                    continue

    if not requested_ids:
        return {}

    return dal.load_lift_log(exercise_ids=list(requested_ids))


def _metric_values(metrics: list[dict], key: str) -> list[float]:
    return [m.get(key) for m in metrics if m.get(key) is not None]


def _compute_recovery_flag(
    metrics_7d: list[dict], metrics_baseline: list[dict]
) -> bool:
    """Return True when recovery markers are within the expected range."""

    rhr_7 = math_utils.mean_or_none(_metric_values(metrics_7d, "hr_resting"))
    sleep_7 = math_utils.mean_or_none(
        _metric_values(metrics_7d, "sleep_asleep_minutes")
    )
    rhr_baseline = math_utils.mean_or_none(
        _metric_values(metrics_baseline, "hr_resting")
    )
    sleep_baseline = math_utils.mean_or_none(
        _metric_values(metrics_baseline, "sleep_asleep_minutes")
    )

    if (
        rhr_baseline is None
        or rhr_7 is None
        or sleep_baseline is None
        or sleep_7 is None
    ):
        return True

    rhr_limit = rhr_baseline * (1 + settings.RHR_ALLOWED_INCREASE)
    sleep_limit = sleep_baseline * settings.SLEEP_ALLOWED_DECREASE
    if rhr_7 > rhr_limit or sleep_7 < sleep_limit:
        return False
    return True


def _adjust_exercise(
    exercise: dict, history_entries: list[dict], recovery_good: bool
) -> Tuple[float | None, str]:
    """Apply progression rules for a single exercise."""

    ex_id = exercise.get("id")
    name = exercise.get("name", f"Exercise #{ex_id}")
    target_display = exercise.get("weight_target", 0)

    if not history_entries:
        detail = f"no RIR, recovery {'good' if recovery_good else 'poor'}"
        message = f"{name}: no history, kept at {target_display}kg ({detail})"
        return None, message

    recent_entries = history_entries[-4:]
    weights = [
        entry.get("weight") for entry in recent_entries if entry.get("weight") is not None
    ]
    rirs = [entry.get("rir") for entry in recent_entries if entry.get("rir") is not None]

    if not weights:
        detail = f"no RIR, recovery {'good' if recovery_good else 'poor'}"
        message = (
            f"{name}: no valid weight data, kept at {target_display}kg ({detail})"
        )
        return None, message

    avg_weight = mean(weights)
    use_rir = bool(rirs)
    avg_rir = mean(rirs) if use_rir else None

    target = exercise.get("weight_target", avg_weight)
    inc = settings.PROGRESSION_INCREMENT
    dec = settings.PROGRESSION_DECREMENT

    if use_rir:
        if avg_rir is not None and avg_rir <= 1:
            inc += settings.PROGRESSION_INCREMENT / 2
        elif avg_rir is not None and avg_rir >= 2:
            inc /= 2

    if not recovery_good:
        inc /= 2
        dec *= 1.5

    detail = (
        f"avg RIR {avg_rir:.1f}" if use_rir and avg_rir is not None else "no RIR"
    ) + f", recovery {'good' if recovery_good else 'poor'}"

    if avg_weight >= target and (not use_rir or (avg_rir is not None and avg_rir <= 2)):
        new_target = round(target * (1 + inc), 2)
        message = f"{name}: +{inc*100:.1f}% ({detail})"
        return new_target, message

    if avg_weight < target or (use_rir and avg_rir is not None and avg_rir > 2):
        new_target = round(target * (1 - dec), 2)
        message = f"{name}: -{dec*100:.1f}% ({detail})"
        return new_target, message

    message = f"{name}: no change ({detail})"
    return None, message


def apply_progression(
    dal: DataAccessLayer, week: dict, lift_history: dict | None = None
) -> Tuple[dict, list[str]]:
    """Adjust weights based on lift log and recovery metrics."""

    lift_history = _collect_lift_history(dal, week, lift_history)

    recent_metrics = dal.get_historical_metrics(7)
    baseline_metrics = dal.get_historical_metrics(settings.BASELINE_DAYS)
    recovery_good = _compute_recovery_flag(recent_metrics, baseline_metrics)

    # The richer Apple Health exports also include heart rate variability (HRV)
    # and detailed sleep stages. In future iterations, these could augment the
    # simple recovery flag above - e.g. flag poor recovery when HRV trends down
    # or when deep/REM sleep proportions fall below expectations.

    adjustments: list[str] = []

    for day in week.get("days", []):
        for session in day.get("sessions", []):
            if session.get("type") != "weights":
                continue
            for exercise in session.get("exercises", []):
                ex_id = str(exercise.get("id"))
                entries = lift_history.get(ex_id, [])
                new_target, message = _adjust_exercise(
                    exercise, entries, recovery_good
                )
                if new_target is not None:
                    exercise["weight_target"] = new_target
                adjustments.append(message)

    return week, adjustments


@dataclass(frozen=True)
class WorkoutProgression:
    """Represents a single workout adjustment applied during calibration."""

    workout_id: int
    exercise_id: int | None
    name: str
    before: float | None
    after: float | None


@dataclass(frozen=True)
class PlanProgressionDecision:
    """Outcome of running progression for a specific plan week."""

    notes: List[str]
    updates: List[WorkoutProgression]
    persisted: bool
def _normalise_plan_week(rows: List[Dict[str, Any]]) -> Tuple[dict, Dict[int, dict]]:
    """Convert raw plan rows into the structure expected by apply_progression."""

    days: Dict[int, dict] = {}
    workout_map: Dict[int, dict] = {}

    for row in rows:
        workout_id = row.get("id")
        if workout_id is None:
            continue
        if row.get("is_cardio"):
            continue

        day_number = row.get("day_of_week")
        if not isinstance(day_number, int):
            continue

        day_entry = days.setdefault(day_number, {"day_of_week": day_number, "sessions": []})
        session = next((s for s in day_entry["sessions"] if s.get("type") == "weights"), None)
        if session is None:
            session = {"type": "weights", "exercises": []}
            day_entry["sessions"].append(session)

        exercise = {
            "id": row.get("exercise_id"),
            "name": row.get("exercise_name") or f"Exercise #{row.get('exercise_id')}"
        }
        weight_target = row.get("target_weight_kg")
        if weight_target is not None:
            converted = converters.to_float(weight_target)
            if converted is not None:
                exercise["weight_target"] = converted
        for key in ("sets", "reps", "rir"):
            if row.get(key) is not None:
                exercise[key] = row.get(key)

        session["exercises"].append(exercise)
        workout_map[int(workout_id)] = exercise

    week = {"days": [days[idx] for idx in sorted(days.keys())]}
    return week, workout_map


def calibrate_plan_week(
    dal: DataAccessLayer,
    plan_id: int,
    week_number: int,
    persist: bool = True,
) -> PlanProgressionDecision:
    """Run progression for the specified plan week and optionally persist updates."""

    rows = dal.get_plan_week(plan_id, week_number)
    if not rows:
        return PlanProgressionDecision(notes=[], updates=[], persisted=False)

    week_structure, workout_map = _normalise_plan_week(rows)
    if not week_structure["days"]:
        return PlanProgressionDecision(notes=[], updates=[], persisted=False)

    _, notes = apply_progression(dal, week_structure)

    updates: List[WorkoutProgression] = []
    for row in rows:
        workout_id = row.get("id")
        if workout_id is None:
            continue
        exercise = workout_map.get(int(workout_id))
        if not exercise:
            continue

        before = converters.to_float(row.get("target_weight_kg"))
        after = converters.to_float(exercise.get("weight_target"))
        if before is None and after is None:
            continue
        if before is not None and after is not None and abs(after - before) < 1e-6:
            continue

        updates.append(
            WorkoutProgression(
                workout_id=int(workout_id),
                exercise_id=row.get("exercise_id"),
                name=exercise.get("name", f"Exercise #{row.get('exercise_id')}") or "Exercise",
                before=before,
                after=after,
            )
        )

    persisted = False
    if persist and updates:
        payload = [
            {"workout_id": item.workout_id, "target_weight_kg": item.after}
            for item in updates
        ]

        try:
            dal.update_workout_targets(payload)
        except Exception as exc:  # pragma: no cover - defensive guardrail
            log_utils.log_message(
                f"Failed to update workout targets: {exc}",
                "ERROR",
            )
        else:
            persisted = True
            try:
                dal.refresh_plan_view()
            except Exception as exc:  # pragma: no cover - defensive guardrail
                log_utils.log_message(
                    f"Failed to refresh plan view after progression updates: {exc}",
                    "WARN",
                )

    return PlanProgressionDecision(notes=notes, updates=updates, persisted=persisted)


