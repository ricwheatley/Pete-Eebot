from datetime import date

from pete_e.config import settings
from pete_e.domain.entities import (
    Exercise,
    Plan,
    Week,
    Workout,
    compute_recovery_flag,
)


def test_exercise_apply_progression_updates_weight() -> None:
    exercise = Exercise(id=1, name="Press", weight_target=100.0)
    history = [
        {"weight": 100, "rir": 0.5},
        {"weight": 100, "rir": 1.0},
        {"weight": 100, "rir": 1.0},
        {"weight": 100, "rir": 0.5},
    ]

    message = exercise.apply_progression(history, recovery_good=True)

    assert exercise.weight_target == 107.5
    assert "+7.5%" in message


def test_exercise_apply_progression_handles_missing_history() -> None:
    exercise = Exercise(id=2, name="Row", weight_target=80.0)

    message = exercise.apply_progression([], recovery_good=False)

    assert exercise.weight_target == 80.0
    assert "no history" in message


def test_week_apply_progression_returns_notes() -> None:
    exercise = Exercise(id=3, name="Squat", weight_target=120.0)
    workout = Workout(
        id=10,
        day_of_week=1,
        slot="main",
        is_cardio=False,
        type="weights",
        percent_1rm=85.0,
        exercise=exercise,
    )
    week = Week(week_number=1, start_date=date.today(), workouts=[workout])

    history = {"3": [{"weight": 120, "rir": 0.0} for _ in range(4)]}

    notes = week.apply_progression(history, recovery_good=True)

    assert any("+" in note for note in notes)
    assert workout.exercise.weight_target is not None


def test_plan_muscle_totals_accumulates_sets() -> None:
    upper = Exercise(id=1, name="Bench", sets=5, reps=5, muscle_group="upper_push")
    lower = Exercise(id=2, name="Deadlift", sets=3, reps=5, muscle_group="lower")
    week = Week(
        week_number=1,
        workouts=[
            Workout(id=1, day_of_week=1, exercise=upper),
            Workout(id=2, day_of_week=2, exercise=lower),
        ],
    )
    plan = Plan(start_date=date.today(), weeks=[week])

    totals = plan.muscle_totals(required_groups=("upper_push", "upper_pull", "lower"))

    assert totals["upper_push"] == 5
    assert totals["lower"] == 3
    assert totals["upper_pull"] == 0


def test_compute_recovery_flag_detects_poor_recovery() -> None:
    baseline = [
        {"hr_resting": 50, "sleep_asleep_minutes": 400}
        for _ in range(settings.BASELINE_DAYS)
    ]
    recent = [
        {"hr_resting": 60, "sleep_asleep_minutes": 300}
        for _ in range(7)
    ]

    assert not compute_recovery_flag(recent, baseline)
