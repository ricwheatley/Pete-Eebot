"""Tests for infrastructure mappers bridging persistence, domain, and API payloads."""

from __future__ import annotations

from datetime import date

import pytest

from pete_e.infrastructure.mappers import PlanMapper, PlanMappingError, WgerPayloadMapper


@pytest.fixture()
def sample_rows() -> tuple[dict[str, object], list[dict[str, object]]]:
    plan_row = {
        "id": 10,
        "start_date": date(2024, 6, 3),
        "metadata": {"source": "unit-test"},
    }
    workout_rows = [
        {
            "id": 1,
            "week_number": 1,
            "day_of_week": 1,
            "exercise_id": 100,
            "exercise_name": "Back Squat",
            "sets": 5,
            "reps": 5,
            "rir": 2,
            "percent_1rm": 85,
            "target_weight_kg": 120.0,
            "is_cardio": False,
            "slot": "07:00:00",
        },
        {
            "id": 2,
            "week_number": 1,
            "day_of_week": 3,
            "exercise_id": 200,
            "exercise_name": "Rowing",
            "sets": 1,
            "reps": 1,
            "is_cardio": True,
            "slot": "18:00:00",
        },
    ]
    return plan_row, workout_rows


def test_database_rows_to_payload_round_trip(sample_rows: tuple[dict[str, object], list[dict[str, object]]]) -> None:
    plan_row, workout_rows = sample_rows
    plan_mapper = PlanMapper()

    plan = plan_mapper.from_rows(plan_row, workout_rows)
    assert plan.start_date == date(2024, 6, 3)
    assert len(plan.weeks) == 1
    assert len(plan.weeks[0].workouts) == 2

    persistence_payload = plan_mapper.to_persistence_payload(plan)
    reconstructed = plan_mapper.from_dict(persistence_payload)
    assert reconstructed == plan

    payload_mapper = WgerPayloadMapper()
    week_payload = payload_mapper.build_week_payload(plan, week_number=1, plan_id=42)

    assert week_payload["plan_id"] == 42
    assert week_payload["week_number"] == 1
    assert len(week_payload["days"]) == 2
    squat_entry = next(day for day in week_payload["days"] if day["day_of_week"] == 1)["exercises"][0]
    assert squat_entry["exercise"] == 100
    assert squat_entry["sets"] == 5
    assert squat_entry["reps"] == 5
    assert squat_entry["rir"] == 2


def test_invalid_rows_raise_validation_error() -> None:
    plan_mapper = PlanMapper()

    with pytest.raises(PlanMappingError):
        plan_mapper.from_rows({"start_date": date(2024, 6, 3)}, [{"day_of_week": 1}])

    with pytest.raises(PlanMappingError):
        plan_mapper.from_rows(
            {"start_date": date(2024, 6, 3)},
            [{"week_number": 1, "day_of_week": None}],
        )
