"""Unit tests for typed full-plan normalization and cursor-only execution."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, time
from typing import Sequence

import pytest
from psycopg.types.json import Json

from pete_e.infrastructure import plan_persistence
from pete_e.infrastructure.plan_persistence import (
    FullPlanWrite,
    PlanWeekWrite,
    PlanWorkoutWrite,
    normalize_full_plan,
    write_full_plan,
)


class StubCursor:
    def __init__(self, returned_rows: list[Sequence[object] | None]) -> None:
        self.returned_rows = iter(returned_rows)
        self.executions: list[tuple[str, tuple[object, ...] | None]] = []

    def execute(
        self,
        query: str,
        params: tuple[object, ...] | None = None,
    ) -> object:
        self.executions.append((" ".join(query.split()), params))
        return self

    def fetchone(self) -> Sequence[object] | None:
        return next(self.returned_rows)


def test_normalization_builds_an_immutable_ordered_normal_form() -> None:
    first_details = {"display_name": "First"}
    second_details = {"display_name": "Second"}

    normalized = normalize_full_plan(
        {
            "start_date": date(2026, 8, 31),
            "weeks": "fallback",
            "metadata": {"source": "unit"},
            "plan_weeks": [
                {"week_number": "2", "workouts": []},
                {
                    "week_number": "10",
                    "is_test": "yes",
                    "workouts": (
                        workout
                        for workout in [
                            {
                                "day_of_week": True,
                                "exercise_id": "73",
                                "sets": 3.9,
                                "reps": "5",
                                "rir": 2,
                                "rir_cue": 1,
                                "scheduled_time": "07:08:09",
                                "slot": "22:00",
                                "optional": "false",
                                "details": first_details,
                                "programmed_difficulty": "4",
                            },
                            {
                                "day_of_week": 3,
                                "exercise_id": "invalid",
                                "sets": None,
                                "reps": object(),
                                "rir": 3,
                                "scheduled_time": "invalid",
                                "slot": "18:30",
                                "is_cardio": 1,
                                "recovery_focused": 1,
                                "details": second_details,
                                "programmed_difficulty": "invalid",
                            },
                        ]
                    ),
                },
            ],
        }
    )

    assert normalized.start_date == date(2026, 8, 31)
    assert normalized.total_weeks == 2
    assert normalized.metadata == {"source": "unit"}
    assert [week.week_number for week in normalized.plan_weeks] == [10, 2]
    assert normalized.plan_weeks[0].is_test is True
    first, second = normalized.plan_weeks[0].workouts
    assert first == PlanWorkoutWrite(
        day_of_week=1,
        exercise_id=73,
        sets=3,
        reps=5,
        rir=2,
        rir_cue=1,
        percent_1rm=None,
        target_weight_kg=None,
        scheduled_time=time(7, 8, 9),
        is_cardio=False,
        comment=None,
        optional=True,
        recovery_focused=False,
        details=first_details,
        programmed_difficulty=4,
    )
    assert second.exercise_id is None
    assert second.reps is None
    assert second.rir_cue == 3
    assert second.scheduled_time == time(18, 30)
    assert second.is_cardio is True
    assert second.recovery_focused is True
    assert second.programmed_difficulty is None
    with pytest.raises(FrozenInstanceError):
        normalized.total_weeks = 4  # type: ignore[misc]


@pytest.mark.parametrize(
    ("payload", "error_type", "message"),
    [
        (None, TypeError, "plan_dict must be a mapping"),
        ({"plan_weeks": "bad"}, ValueError, "non-empty 'plan_weeks' list"),
        ({"plan_weeks": []}, ValueError, "non-empty 'plan_weeks' list"),
        ({"plan_weeks": [{}]}, ValueError, "include a 'start_date'"),
        (
            {"start_date": "x", "plan_weeks": [{"workouts": []}]},
            ValueError,
            "week payload missing week_number",
        ),
        (
            {
                "start_date": "x",
                "plan_weeks": [{"week_number": 1, "workouts": [1]}],
            },
            TypeError,
            "workouts must be mappings",
        ),
        (
            {
                "start_date": "x",
                "plan_weeks": [{"week_number": 1, "workouts": [{}]}],
            },
            ValueError,
            "workout payload missing day_of_week",
        ),
    ],
)
def test_normalization_preserves_validation_errors(
    payload: object,
    error_type: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error_type, match=message):
        normalize_full_plan(payload)


def test_integer_and_time_coercion_preserve_legacy_edge_cases() -> None:
    class ExplodingInt:
        def __int__(self) -> int:
            raise RuntimeError("custom conversion failure")

    assert plan_persistence._coerce_int(None) is None
    assert plan_persistence._coerce_int(False) == 0
    assert plan_persistence._coerce_int(7) == 7
    assert plan_persistence._coerce_int("8") == 8
    assert plan_persistence._coerce_int(object()) is None
    assert plan_persistence._coerce_int("invalid") is None
    with pytest.raises(RuntimeError, match="custom conversion failure"):
        plan_persistence._coerce_int(ExplodingInt())

    direct_time = time(6, 30)
    assert plan_persistence._coerce_scheduled_time(None) is None
    assert plan_persistence._coerce_scheduled_time(direct_time) is direct_time
    assert plan_persistence._coerce_scheduled_time("  ") is None
    assert plan_persistence._coerce_scheduled_time("09:10:11") == time(9, 10, 11)
    assert plan_persistence._coerce_scheduled_time("invalid") is None


def test_integer_week_count_and_empty_workouts_are_preserved() -> None:
    normalized = normalize_full_plan(
        {
            "start_date": "accepted-until-postgres",
            "weeks": False,
            "plan_weeks": [{"week_number": 1, "workouts": None}],
        }
    )

    assert normalized.total_weeks is False
    assert normalized.plan_weeks[0].workouts == ()


def test_writer_executes_only_ordered_dml_and_duplicates_baselines() -> None:
    cursor = StubCursor([(41,), (51,)])
    details = {"display_name": "Lift"}
    plan = FullPlanWrite(
        start_date=date(2026, 8, 31),
        total_weeks=1,
        metadata={"source": "unit"},
        plan_weeks=(
            PlanWeekWrite(
                week_number=1,
                is_test=True,
                workouts=(
                    PlanWorkoutWrite(
                        day_of_week=1,
                        exercise_id=73,
                        sets=5,
                        reps=3,
                        rir=2.0,
                        rir_cue=1.0,
                        percent_1rm=85,
                        target_weight_kg=100,
                        scheduled_time=time(7),
                        is_cardio=False,
                        comment="lift",
                        optional=False,
                        recovery_focused=False,
                        details=details,
                        programmed_difficulty=4,
                    ),
                    PlanWorkoutWrite(
                        day_of_week=2,
                        exercise_id=None,
                        sets=0,
                        reps=0,
                        rir=None,
                        rir_cue=None,
                        percent_1rm=None,
                        target_weight_kg=None,
                        scheduled_time=None,
                        is_cardio=False,
                        comment=None,
                        optional=False,
                        recovery_focused=False,
                        details=None,
                        programmed_difficulty=None,
                    ),
                ),
            ),
        ),
    )

    assert write_full_plan(cursor, plan) == 41

    statements = [statement for statement, _ in cursor.executions]
    assert len(statements) == 5
    assert statements[0].startswith("UPDATE training_plans")
    assert statements[1].startswith("INSERT INTO training_plans")
    assert statements[2].startswith("INSERT INTO training_plan_weeks")
    assert statements[3].startswith("INSERT INTO training_plan_workouts")
    assert statements[4].startswith("INSERT INTO training_plan_workouts")
    assert all(
        not statement.startswith(("CREATE", "ALTER", "DROP"))
        for statement in statements
    )

    plan_params = cursor.executions[1][1]
    assert plan_params is not None
    assert isinstance(plan_params[2], Json)
    assert plan_params[2].obj == {"source": "unit"}
    workout_params = cursor.executions[3][1]
    assert workout_params is not None
    assert workout_params[3:8] == (5, 5, 3, 2.0, 2.0)
    assert isinstance(workout_params[16], Json)
    assert workout_params[16].obj == details
    second_workout_params = cursor.executions[4][1]
    assert second_workout_params is not None
    assert second_workout_params[16] is None


def test_writer_accepts_absent_metadata_and_an_empty_normal_form() -> None:
    cursor = StubCursor([(41,)])
    plan = FullPlanWrite(
        start_date="raw-start",
        total_weeks=0,
        metadata=None,
        plan_weeks=(),
    )

    assert write_full_plan(cursor, plan) == 41
    assert len(cursor.executions) == 2
    assert cursor.executions[1][1] == ("raw-start", 0, None)


@pytest.mark.parametrize("returned_row", [None, ()])
def test_writer_preserves_missing_return_id_failures(
    returned_row: Sequence[object] | None,
) -> None:
    cursor = StubCursor([returned_row])
    plan = FullPlanWrite(
        start_date="raw-start",
        total_weeks=0,
        metadata=None,
        plan_weeks=(),
    )

    with pytest.raises((TypeError, IndexError)):
        write_full_plan(cursor, plan)
