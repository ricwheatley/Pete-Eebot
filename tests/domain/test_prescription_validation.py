from __future__ import annotations

from math import nan

import pytest

from pete_e.domain import schedule_rules
from pete_e.domain.entities import Exercise, Plan, Week, Workout
from pete_e.domain.prescription_validation import (
    PrescriptionValidationError,
    validate_plan_prescriptions,
    validate_training_maxes,
    validate_wger_payload_prescriptions,
)


def _training_maxes() -> dict[str, float]:
    return {
        "bench": 100.0,
        "squat": 140.0,
        "deadlift": 180.0,
        "ohp": 60.0,
    }


def test_training_max_validation_requires_every_finite_positive_main_lift() -> None:
    values = _training_maxes()
    values["deadlift"] = nan

    with pytest.raises(PrescriptionValidationError, match="deadlift"):
        validate_training_maxes(values)


def test_generated_percentage_lift_requires_a_positive_target() -> None:
    plan = Plan(
        weeks=[
            Week(
                week_number=1,
                workouts=[
                    Workout(
                        id=None,
                        day_of_week=1,
                        percent_1rm=65.0,
                        exercise=Exercise(
                            id=schedule_rules.BENCH_ID,
                            name="Bench Press",
                            sets=1,
                            reps=5,
                            weight_target=None,
                        ),
                    )
                ],
            )
        ]
    )

    with pytest.raises(PrescriptionValidationError, match="missing or invalid target weight"):
        validate_plan_prescriptions(plan)


def test_wger_payload_rejects_missing_target_before_remote_export() -> None:
    payload = {
        "days": [
            {
                "day_of_week": 1,
                "exercises": [
                    {
                        "exercise": schedule_rules.BENCH_ID,
                        "exercise_name": "Bench Press",
                        "sets": 1,
                        "reps": 5,
                        "percent_1rm": 65.0,
                        "target_weight_kg": None,
                        "is_cardio": False,
                    }
                ],
            }
        ]
    }

    with pytest.raises(PrescriptionValidationError, match="Bench Press"):
        validate_wger_payload_prescriptions(payload)


def test_generated_lift_rejects_non_positive_percentage() -> None:
    plan = Plan(
        weeks=[
            Week(
                week_number=1,
                workouts=[
                    Workout(
                        id=None,
                        day_of_week=1,
                        percent_1rm=0.0,
                        exercise=Exercise(
                            id=schedule_rules.BENCH_ID,
                            name="Bench Press",
                            sets=1,
                            reps=5,
                            weight_target=80.0,
                        ),
                    )
                ],
            )
        ]
    )

    with pytest.raises(PrescriptionValidationError, match="invalid percentage"):
        validate_plan_prescriptions(plan)
