"""Adaptive weight progression logic operating on pre-fetched data."""

from dataclasses import dataclass

from typing import Any, Dict, List, Tuple

from pete_e.domain.entities import (
    Exercise,
    Week,
    Workout,
    compute_recovery_flag,
)
from pete_e.utils import converters


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            try:
                return int(float(stripped))
            except ValueError:
                return None
    return None


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


def _normalise_plan_week(rows: List[Dict[str, Any]]) -> Tuple[Week, Dict[int, Workout]]:
    """Convert raw plan rows into the structure expected by apply_progression."""

    workouts: list[Workout] = []
    workout_map: Dict[int, Workout] = {}

    if not rows:
        return Week(week_number=0, workouts=[]), workout_map

    week_number = _to_int(rows[0].get("week_number")) or 0
    start_date = converters.to_date(rows[0].get("week_start"))

    for row in rows:
        workout_id = _to_int(row.get("id"))
        if workout_id is None:
            continue

        day_number = _to_int(row.get("day_of_week"))
        if day_number is None:
            continue

        is_cardio = bool(row.get("is_cardio"))
        workout_type = "cardio" if is_cardio else "weights"

        exercise_id = _to_int(row.get("exercise_id"))
        exercise_name = row.get("exercise_name") or (
            f"Exercise #{exercise_id}" if exercise_id is not None else "Exercise"
        )
        exercise = Exercise(
            id=exercise_id,
            name=str(exercise_name),
            sets=_to_int(row.get("sets")),
            reps=_to_int(row.get("reps")),
            rir=converters.to_float(row.get("rir")),
            weight_target=converters.to_float(row.get("target_weight_kg")),
            muscle_group=row.get("muscle_group"),
        )

        workout = Workout(
            id=workout_id,
            day_of_week=day_number,
            slot=row.get("slot"),
            is_cardio=is_cardio,
            type=workout_type,
            percent_1rm=converters.to_float(row.get("percent_1rm")),
            exercise=exercise,
            intensity=row.get("intensity"),
        )

        workouts.append(workout)
        workout_map[workout_id] = workout

    return Week(week_number=week_number, start_date=start_date, workouts=workouts), workout_map


def _compute_recovery_flag(
    metrics_7d: List[Dict[str, Any]],
    metrics_baseline: List[Dict[str, Any]],
) -> bool:
    """Compatibility wrapper delegating to the entity helper implementation."""

    return compute_recovery_flag(metrics_7d, metrics_baseline)


def _adjust_exercise(
    exercise: Dict[str, Any],
    history_entries: List[Dict[str, Any]],
    recovery_good: bool,
) -> Tuple[float | None, str]:
    """Proxy the historical helper API through the Exercise entity implementation."""

    exercise_entity = Exercise(
        id=_to_int(exercise.get("id")),
        name=str(
            exercise.get("name")
            or (
                f"Exercise #{exercise.get('id')}"
                if exercise.get("id") is not None
                else "Exercise"
            )
        ),
        sets=_to_int(exercise.get("sets")),
        reps=_to_int(exercise.get("reps")),
        rir=converters.to_float(exercise.get("rir")),
        weight_target=converters.to_float(exercise.get("weight_target")),
        muscle_group=exercise.get("muscle_group"),
    )

    before = exercise_entity.weight_target
    message = exercise_entity.apply_progression(
        history_entries, recovery_good=recovery_good
    )
    after = exercise_entity.weight_target

    if after is None:
        return None, message
    if before is not None and abs(after - before) < 1e-9:
        return None, message

    return after, message


def calibrate_plan_week(
    rows: List[Dict[str, Any]],
    *,
    lift_history: Dict[str, List[Dict[str, Any]]] | None = None,
    recent_metrics: List[Dict[str, Any]] | None = None,
    baseline_metrics: List[Dict[str, Any]] | None = None,
) -> PlanProgressionDecision:
    """Run progression for the specified plan week using supplied data."""

    if not rows:
        return PlanProgressionDecision(notes=[], updates=[], persisted=False)

    week_entity, workout_map = _normalise_plan_week(rows)
    if not week_entity.workouts:
        return PlanProgressionDecision(notes=[], updates=[], persisted=False)

    _, notes = apply_progression(
        week_entity,
        lift_history=lift_history,
        recent_metrics=recent_metrics,
        baseline_metrics=baseline_metrics,
    )

    updates: List[WorkoutProgression] = []
    for row in rows:
        workout_id = row.get("id")
        if workout_id is None:
            continue
        workout = workout_map.get(int(workout_id))
        if not workout:
            continue

        before = converters.to_float(row.get("target_weight_kg"))
        after = converters.to_float(workout.weight_target)
        if before is None and after is None:
            continue
        if before is not None and after is not None and abs(after - before) < 1e-6:
            continue

        updates.append(
            WorkoutProgression(
                workout_id=int(workout_id),
                exercise_id=row.get("exercise_id"),
                name=workout.exercise.name
                if workout.exercise and workout.exercise.name
                else f"Exercise #{row.get('exercise_id')}",
                before=before,
                after=after,
            )
        )

    return PlanProgressionDecision(notes=notes, updates=updates, persisted=False)


def apply_progression(
    week: Week,
    *,
    lift_history: Dict[str, List[Dict[str, Any]]] | None = None,
    recent_metrics: List[Dict[str, Any]] | None = None,
    baseline_metrics: List[Dict[str, Any]] | None = None,
) -> Tuple[Week, List[str]]:
    """Adjust weights based on lift log and recovery metrics."""

    history = lift_history or {}
    metrics_7d = recent_metrics or []
    metrics_baseline = baseline_metrics or []
    recovery_good = compute_recovery_flag(metrics_7d, metrics_baseline)

    notes = week.apply_progression(history, recovery_good=recovery_good)
    return week, notes


