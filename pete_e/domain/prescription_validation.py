"""Fail-closed validation for generated and exported training prescriptions."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from pete_e.domain import schedule_rules
from pete_e.domain.entities import Plan


class PrescriptionValidationError(ValueError):
    """Raised when a strength prescription is unsafe to persist or publish."""

    def __init__(self, issues: Sequence[str]):
        cleaned = tuple(str(issue).strip() for issue in issues if str(issue).strip())
        self.issues = cleaned
        super().__init__("Invalid training prescription: " + "; ".join(cleaned))


def _positive_number(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def _positive_int(value: Any) -> bool:
    if not _positive_number(value):
        return False
    number = float(value)
    return number.is_integer()


def required_training_max_codes() -> tuple[str, ...]:
    """Return the stable lift codes needed to build percentage prescriptions."""

    codes = {
        schedule_rules.LIFT_CODE_BY_ID[exercise_id]
        for exercise_id in schedule_rules.MAIN_LIFT_BY_DOW.values()
        if exercise_id in schedule_rules.LIFT_CODE_BY_ID
    }
    return tuple(sorted(codes))


def calculate_target_weight(training_max: Any, percent_1rm: Any) -> float:
    """Calculate a 2.5 kg-rounded target from already validated inputs."""

    if not _positive_number(training_max) or not _positive_number(percent_1rm):
        raise PrescriptionValidationError(
            ["training max and percentage must both be finite positive numbers"]
        )
    target = round((float(training_max) * float(percent_1rm) / 100.0) / 2.5) * 2.5
    if not _positive_number(target):
        raise PrescriptionValidationError(
            ["training max and percentage produce a non-positive target weight"]
        )
    return target


def validate_training_maxes(training_maxes: Mapping[str, Any]) -> None:
    """Require a finite, positive training max for every programmed main lift."""

    if not isinstance(training_maxes, Mapping):
        raise PrescriptionValidationError(["training max data is unavailable"])
    missing = [
        lift_code
        for lift_code in required_training_max_codes()
        if not _positive_number(training_maxes.get(lift_code))
    ]
    if missing:
        raise PrescriptionValidationError(
            ["missing or invalid training max(es): " + ", ".join(missing)]
        )


def validate_plan_prescriptions(plan: Plan) -> None:
    """Validate exercise values in a generated domain plan before persistence."""

    issues: list[str] = []
    for week in plan.weeks:
        for workout in week.workouts:
            exercise = workout.exercise
            if exercise is None or workout.is_cardio:
                continue
            details = workout.details if isinstance(workout.details, Mapping) else {}
            if str(details.get("session_type") or "").strip().lower() == schedule_rules.STRETCH_SESSION_TYPE:
                continue

            label = f"week {week.week_number}, day {workout.day_of_week}, {exercise.name}"
            if not _positive_int(exercise.sets):
                issues.append(f"{label}: missing or invalid sets")
            if not _positive_int(exercise.reps):
                issues.append(f"{label}: missing or invalid reps")
            if workout.percent_1rm is not None:
                if not _positive_number(workout.percent_1rm):
                    issues.append(f"{label}: missing or invalid percentage")
                if not _positive_number(exercise.weight_target):
                    issues.append(f"{label}: missing or invalid target weight")

    if issues:
        raise PrescriptionValidationError(issues)


def validate_wger_payload_prescriptions(payload: Mapping[str, Any]) -> None:
    """Validate an assembled Wger payload before any remote mutation occurs."""

    issues: list[str] = []
    days = payload.get("days")
    if not isinstance(days, list):
        return

    for day in days:
        if not isinstance(day, Mapping):
            continue
        day_of_week = day.get("day_of_week")
        exercises = day.get("exercises")
        if not isinstance(exercises, list):
            continue
        for entry in exercises:
            if not isinstance(entry, Mapping):
                continue
            details = entry.get("details")
            details_map = details if isinstance(details, Mapping) else {}
            session_type = str(details_map.get("session_type") or "").strip().lower()
            if bool(entry.get("is_cardio")) or session_type == schedule_rules.STRETCH_SESSION_TYPE:
                continue
            if entry.get("exercise") is None:
                continue

            label = str(entry.get("exercise_name") or f"exercise {entry.get('exercise')}")
            prefix = f"day {day_of_week}, {label}"
            if not _positive_int(entry.get("sets")):
                issues.append(f"{prefix}: missing or invalid sets")
            if not _positive_int(entry.get("reps")):
                issues.append(f"{prefix}: missing or invalid reps")
            if entry.get("percent_1rm") is not None:
                if not _positive_number(entry.get("percent_1rm")):
                    issues.append(f"{prefix}: missing or invalid percentage")
                if not _positive_number(entry.get("target_weight_kg")):
                    issues.append(f"{prefix}: missing or invalid target weight")

    if issues:
        raise PrescriptionValidationError(issues)


__all__ = [
    "PrescriptionValidationError",
    "calculate_target_weight",
    "required_training_max_codes",
    "validate_plan_prescriptions",
    "validate_training_maxes",
    "validate_wger_payload_prescriptions",
]
