from datetime import date, timedelta
from typing import Dict, List

import pytest

from pete_e.domain import schedule_rules
from pete_e.domain.validation import ensure_muscle_balance, validate_plan_structure


_INTENSITIES: tuple[str, ...] = ("light", "medium", "heavy", "deload")

_DAY_TEMPLATES: Dict[int, tuple[str, tuple[tuple[str, int, str], ...]]] = {
    1: (
        "upper_push",
        (
            ("main", 5, "upper_push"),
            ("secondary", 3, "upper_pull"),
            ("support", 3, "upper_push"),
            ("core", 3, "core"),
        ),
    ),
    2: (
        "lower",
        (
            ("main", 4, "lower"),
            ("secondary", 4, "upper_push"),
            ("support", 3, "lower"),
            ("core", 3, "core"),
        ),
    ),
    4: (
        "upper_pull",
        (
            ("main", 5, "upper_pull"),
            ("secondary", 3, "lower"),
            ("support", 3, "upper_pull"),
            ("core", 3, "core"),
        ),
    ),
    5: (
        "posterior_chain",
        (
            ("main", 3, "lower"),
            ("secondary", 3, "upper_pull"),
            ("support", 3, "upper_push"),
            ("core", 3, "core"),
        ),
    ),
}


def _make_day(
    day_of_week: int,
    focus: str,
    slots: tuple[tuple[str, int, str], ...],
    intensity: str,
    base_id: int,
) -> List[Dict[str, object]]:
    workouts: List[Dict[str, object]] = []
    for offset, (slot, sets, muscle_group) in enumerate(slots):
        workouts.append(
            {
                "day_of_week": day_of_week,
                "exercise_id": base_id + offset,
                "sets": sets,
                "reps": 6,
                "rir": 2 if slot == "main" else 3,
                "focus": focus,
                "slot": slot,
                "muscle_group": muscle_group,
                "intensity": intensity,
            }
        )
    return workouts


def make_valid_plan(start: date) -> Dict[str, object]:
    weeks: List[Dict[str, object]] = []
    for idx, intensity in enumerate(_INTENSITIES, start=1):
        week_start = start + timedelta(days=(idx - 1) * 7)
        workouts: List[Dict[str, object]] = []
        base_id = idx * 1000
        for day_of_week, (focus, slots) in _DAY_TEMPLATES.items():
            workouts.extend(
                _make_day(
                    day_of_week,
                    focus,
                    slots,
                    intensity,
                    base_id + day_of_week * 10,
                )
            )
        weeks.append(
            {
                "week_number": idx,
                "intensity": intensity,
                "start_date": week_start.isoformat(),
                "workouts": workouts,
            }
        )
    plan = {"weeks": weeks, "metadata": {"fixture": True}}
    balance = ensure_muscle_balance(plan)
    assert balance.balanced, f"Fixture plan must stay balanced: {balance}"
    return plan


def test_validate_plan_structure_accepts_valid_plan() -> None:
    start = date(2025, 9, 22)
    plan = make_valid_plan(start)
    validate_plan_structure(plan, start)


def test_validate_plan_structure_rejects_incorrect_week_count() -> None:
    start = date(2025, 9, 22)
    plan = make_valid_plan(start)
    plan["weeks"].pop()
    with pytest.raises(ValueError) as excinfo:
        validate_plan_structure(plan, start)
    assert "4 weeks" in str(excinfo.value)


def test_validate_plan_structure_rejects_week_number_mismatch() -> None:
    start = date(2025, 9, 22)
    plan = make_valid_plan(start)
    plan["weeks"][1]["week_number"] = 4
    with pytest.raises(ValueError) as excinfo:
        validate_plan_structure(plan, start)
    assert "week 2: expected week_number 2" in str(excinfo.value)


def test_validate_plan_structure_requires_seven_day_spacing() -> None:
    start = date(2025, 9, 22)
    plan = make_valid_plan(start)
    plan["weeks"][2]["start_date"] = (start + timedelta(days=16)).isoformat()
    with pytest.raises(ValueError) as excinfo:
        validate_plan_structure(plan, start)
    assert "start_date" in str(excinfo.value)


def test_validate_plan_structure_requires_training_day_pattern() -> None:
    start = date(2025, 9, 22)
    plan = make_valid_plan(start)
    for workout in plan["weeks"][0]["workouts"]:
        if workout["day_of_week"] == 2:
            workout["day_of_week"] = 3
    with pytest.raises(ValueError) as excinfo:
        validate_plan_structure(plan, start)
    assert "missing training days" in str(excinfo.value)


def test_validate_plan_structure_flags_muscle_imbalance() -> None:
    start = date(2025, 9, 22)
    plan = make_valid_plan(start)
    for week in plan["weeks"]:
        week["workouts"] = [
            workout
            for workout in week["workouts"]
            if workout["muscle_group"] != "upper_pull"
        ]
    with pytest.raises(ValueError) as excinfo:
        validate_plan_structure(plan, start)
    assert "muscle balance" in str(excinfo.value)


def test_validate_plan_structure_flags_missing_weights() -> None:
    start = date(2025, 9, 22)
    weeks: List[Dict[str, object]] = []
    muscle_group_by_day = {1: "upper_push", 2: "lower", 4: "upper_pull", 5: "lower"}

    for week_number in range(1, 5):
        week_start = start + timedelta(days=(week_number - 1) * 7)
        workouts: List[Dict[str, object]] = []
        for day_of_week, exercise_id in schedule_rules.MAIN_LIFT_BY_DOW.items():
            workouts.append(
                {
                    "day_of_week": day_of_week,
                    "exercise_id": exercise_id,
                    "sets": schedule_rules.WEEK_PCTS[week_number]["sets"],
                    "reps": schedule_rules.WEEK_PCTS[week_number]["reps"],
                    "rir": schedule_rules.WEEK_PCTS[week_number]["rir_cue"],
                    "percent_1rm": schedule_rules.WEEK_PCTS[week_number]["percent_1rm"],
                    "target_weight_kg": None,
                    "slot": "main",
                    "is_cardio": False,
                    "muscle_group": muscle_group_by_day.get(day_of_week, "upper_push"),
                }
            )
        weeks.append(
            {
                "week_number": week_number,
                "start_date": week_start.isoformat(),
                "workouts": workouts,
            }
        )

    plan = {"weeks": weeks}

    with pytest.raises(ValueError) as excinfo:
        validate_plan_structure(plan, start)

    assert "missing target weight" in str(excinfo.value)
