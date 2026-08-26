"""Typed normalization and DML execution for atomic full-plan persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Any, Protocol, Sequence, cast

from psycopg.types.json import Json


@dataclass(frozen=True)
class PlanWorkoutWrite:
    """Normalized values for one ``training_plan_workouts`` insert."""

    day_of_week: int
    exercise_id: int | None
    sets: int | None
    reps: int | None
    rir: object
    rir_cue: object
    percent_1rm: object
    target_weight_kg: object
    scheduled_time: time | None
    is_cardio: bool
    comment: object
    optional: bool
    recovery_focused: bool
    details: object
    programmed_difficulty: int | None


@dataclass(frozen=True)
class PlanWeekWrite:
    """Normalized values for one plan week and its ordered workouts."""

    week_number: int
    is_test: bool
    workouts: tuple[PlanWorkoutWrite, ...]


@dataclass(frozen=True)
class FullPlanWrite:
    """Immutable normal form consumed by the PostgreSQL writer."""

    start_date: object
    total_weeks: int
    metadata: object
    plan_weeks: tuple[PlanWeekWrite, ...]


class PlanWriteCursor(Protocol):
    """The narrow cursor surface needed by the atomic writer."""

    def execute(
        self,
        query: str,
        params: tuple[object, ...] | None = None,
    ) -> object: ...

    def fetchone(self) -> Sequence[object] | None: ...


_INSERT_PLAN = """
    INSERT INTO training_plans (start_date, weeks, is_active, metadata)
    VALUES (%s, %s, true, %s)
    RETURNING id;
"""

_INSERT_WEEK = """
    INSERT INTO training_plan_weeks (plan_id, week_number, is_test)
    VALUES (%s, %s, %s)
    RETURNING id;
"""

_INSERT_WORKOUT = """
    INSERT INTO training_plan_workouts (
        week_id,
        day_of_week,
        exercise_id,
        sets,
        baseline_sets,
        reps,
        rir,
        baseline_rir,
        percent_1rm,
        target_weight_kg,
        rir_cue,
        scheduled_time,
        is_cardio,
        comment,
        optional,
        recovery_focused,
        details,
        programmed_difficulty
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def normalize_full_plan(plan_data: object) -> FullPlanWrite:
    """Validate and normalize the legacy full-plan dictionary contract."""

    if not isinstance(plan_data, dict):
        raise TypeError("plan_dict must be a mapping")

    raw_weeks = plan_data.get("plan_weeks")
    if not isinstance(raw_weeks, list) or not raw_weeks:
        raise ValueError("plan_dict must include a non-empty 'plan_weeks' list")

    start_date = plan_data.get("start_date")
    if start_date is None:
        raise ValueError("plan_dict must include a 'start_date'")

    total_weeks = _total_weeks(plan_data.get("weeks"), raw_weeks)
    ordered_weeks = sorted(raw_weeks, key=_raw_week_number)
    return FullPlanWrite(
        start_date=start_date,
        total_weeks=total_weeks,
        metadata=plan_data.get("metadata"),
        plan_weeks=tuple(_normalize_week(week) for week in ordered_weeks),
    )


def _total_weeks(value: object, raw_weeks: list[Any]) -> int:
    if isinstance(value, int):
        return value
    return len(raw_weeks)


def _raw_week_number(value: Any) -> Any:
    return value.get("week_number", 0)


def _normalize_week(payload: Any) -> PlanWeekWrite:
    week_number = _coerce_int(payload.get("week_number"))
    if week_number is None:
        raise ValueError("week payload missing week_number")

    raw_workouts = payload.get("workouts") or []
    workouts: list[PlanWorkoutWrite] = []
    for workout in raw_workouts:
        if not isinstance(workout, dict):
            raise TypeError("workouts must be mappings")
        workouts.append(_normalize_workout(workout))
    return PlanWeekWrite(
        week_number=week_number,
        is_test=bool(payload.get("is_test", False)),
        workouts=tuple(workouts),
    )


def _normalize_workout(payload: dict[str, Any]) -> PlanWorkoutWrite:
    day_of_week = _coerce_int(payload.get("day_of_week"))
    if day_of_week is None:
        raise ValueError("workout payload missing day_of_week")

    rir = payload.get("rir")
    rir_cue = payload.get("rir_cue")
    if rir_cue is None:
        rir_cue = rir
    return PlanWorkoutWrite(
        day_of_week=day_of_week,
        exercise_id=_coerce_int(payload.get("exercise_id")),
        sets=_coerce_int(payload.get("sets")),
        reps=_coerce_int(payload.get("reps")),
        rir=rir,
        rir_cue=rir_cue,
        percent_1rm=payload.get("percent_1rm"),
        target_weight_kg=payload.get("target_weight_kg"),
        scheduled_time=_scheduled_time(payload),
        is_cardio=bool(payload.get("is_cardio")),
        comment=payload.get("comment"),
        optional=bool(payload.get("optional", False)),
        recovery_focused=bool(payload.get("recovery_focused", False)),
        details=payload.get("details"),
        programmed_difficulty=_coerce_int(payload.get("programmed_difficulty")),
    )


def _scheduled_time(payload: dict[str, Any]) -> time | None:
    scheduled_time = _coerce_scheduled_time(payload.get("scheduled_time"))
    if scheduled_time is not None:
        return scheduled_time
    return _coerce_scheduled_time(payload.get("slot"))


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError):
        return None


def _coerce_scheduled_time(value: object) -> time | None:
    if value is None:
        return None
    if isinstance(value, time):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return time.fromisoformat(text)
    except ValueError:
        return None


def write_full_plan(cursor: PlanWriteCursor, plan: FullPlanWrite) -> int:
    """Write a normalized plan through an explicit cursor without committing."""

    cursor.execute(
        "UPDATE training_plans SET is_active = false WHERE is_active = true;"
    )
    cursor.execute(
        _INSERT_PLAN,
        (
            plan.start_date,
            plan.total_weeks,
            Json(plan.metadata) if plan.metadata is not None else None,
        ),
    )
    plan_id = _returned_id(cursor)
    for week in plan.plan_weeks:
        week_id = _insert_week(cursor, plan_id, week)
        for workout in week.workouts:
            _insert_workout(cursor, week_id, workout)
    return plan_id


def _insert_week(
    cursor: PlanWriteCursor,
    plan_id: int,
    week: PlanWeekWrite,
) -> int:
    cursor.execute(
        _INSERT_WEEK,
        (plan_id, week.week_number, week.is_test),
    )
    return _returned_id(cursor)


def _insert_workout(
    cursor: PlanWriteCursor,
    week_id: int,
    workout: PlanWorkoutWrite,
) -> None:
    cursor.execute(
        _INSERT_WORKOUT,
        (
            week_id,
            workout.day_of_week,
            workout.exercise_id,
            workout.sets,
            workout.sets,
            workout.reps,
            workout.rir,
            workout.rir,
            workout.percent_1rm,
            workout.target_weight_kg,
            workout.rir_cue,
            workout.scheduled_time,
            workout.is_cardio,
            workout.comment,
            workout.optional,
            workout.recovery_focused,
            Json(workout.details) if workout.details is not None else None,
            workout.programmed_difficulty,
        ),
    )


def _returned_id(cursor: PlanWriteCursor) -> int:
    row = cast(Sequence[object], cursor.fetchone())
    return cast(int, row[0])
