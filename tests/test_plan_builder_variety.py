from datetime import date
import sys
import types

import pytest

# Stub configuration before importing the modules under test.
if "pete_e.config" not in sys.modules:
    config_stub = types.ModuleType("pete_e.config")

    class _SettingsStub:
        RECOVERY_SLEEP_THRESHOLD_MINUTES = 420
        RECOVERY_RHR_THRESHOLD = 60

    config_stub.settings = _SettingsStub()
    sys.modules["pete_e.config"] = config_stub

from pete_e.domain.plan_builder import build_block
from pete_e.domain.validation import ensure_muscle_balance


class StubDal:
    def __init__(self, prefer_light: bool = False):
        self.saved_plan = None
        self.saved_start = None
        self.plan_id = 101
        self.prefer_light = prefer_light

    def find_plan_by_start_date(self, start_date: date):
        return None

    def get_historical_metrics(self, days: int):
        base = {
            "hr_resting": 58 if self.prefer_light else 52,
            "sleep_asleep_minutes": 380 if self.prefer_light else 450,
        }
        return [base for _ in range(days)]

    def save_training_plan(self, plan: dict, start_date: date) -> int:
        self.saved_plan = plan
        self.saved_start = start_date
        return self.plan_id


@pytest.mark.parametrize("prefer_light", [False, True])
def test_build_block_rotates_and_periodises(prefer_light: bool):
    dal = StubDal(prefer_light=prefer_light)
    plan_id = build_block(dal, date(2025, 9, 22))

    assert plan_id == dal.plan_id
    assert dal.saved_plan is not None

    weeks = dal.saved_plan["weeks"]
    assert [w["intensity"] for w in weeks] == ["light", "medium", "heavy", "deload"]

    main_sets_per_week = []
    main_exercises_by_focus = {}
    for week in weeks:
        week_main_sets = 0
        for workout in week["workouts"]:
            if workout.get("slot") != "main":
                continue
            week_main_sets += workout["sets"]
            main_exercises_by_focus.setdefault(workout["focus"], []).append(workout["exercise_id"])
        main_sets_per_week.append(week_main_sets)

    assert main_sets_per_week[0] < main_sets_per_week[1] < main_sets_per_week[2]
    assert main_sets_per_week[3] < main_sets_per_week[2]

    for exercises in main_exercises_by_focus.values():
        assert len(set(exercises)) > 1

    balance_report = ensure_muscle_balance(dal.saved_plan)
    assert balance_report.balanced is True

    if prefer_light:
        # Light preference should increase average RIR for main lifts compared to heavy week baseline
        light_rirs = [
            w["rir"]
            for w in weeks[0]["workouts"]
            if w.get("slot") == "main"
        ]
        heavy_rirs = [
            w["rir"]
            for w in weeks[2]["workouts"]
            if w.get("slot") == "main"
        ]
        assert min(light_rirs) >= min(heavy_rirs)


def test_muscle_balance_flags_imbalance():
    unbalanced_plan = {
        "weeks": [
            {
                "week_number": 1,
                "intensity": "light",
                "workouts": [
                    {
                        "day_of_week": 1,
                        "exercise_id": 4001,
                        "sets": 6,
                        "reps": 6,
                        "rir": 2,
                        "focus": "lower",
                        "slot": "main",
                        "muscle_group": "lower",
                    },
                    {
                        "day_of_week": 3,
                        "exercise_id": 4002,
                        "sets": 5,
                        "reps": 8,
                        "rir": 2,
                        "focus": "lower",
                        "slot": "secondary",
                        "muscle_group": "lower",
                    },
                ],
            }
        ]
    }

    report = ensure_muscle_balance(unbalanced_plan, tolerance=0.2)
    assert report.balanced is False
    assert set(report.missing_groups) == {"upper_push", "upper_pull"}
