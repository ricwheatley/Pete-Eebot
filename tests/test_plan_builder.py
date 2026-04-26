import pytest
import sys
import types
from datetime import date, timedelta
from pathlib import Path

# Lightweight stubs for dependencies remain the same
config_stub = types.ModuleType("pete_e.config")

class _StubSettings:
    def __init__(self):
        self.log_path = Path("/tmp/pete_eebot-test.log")

config_stub.Settings = _StubSettings
config_stub.settings = _StubSettings()
sys.modules.setdefault("pete_e.config", config_stub)
sys.modules.setdefault("pete_e.config.config", config_stub)

# Import the new classes and modules that are now used
from pete_e.domain import schedule_rules
from pete_e.domain.plan_factory import PlanFactory
from pete_e.domain.repositories import PlanRepository


class DummyRepo(PlanRepository):
    """
    Fake PlanRepository to simulate database lookups and record calls.
    This replaces the old DummyDAL that was mocking plan_rw.
    """
    def __init__(self):
        self.assist_calls = []
        self.saved_plans = []
        self.saved_workouts = []

    def get_latest_training_maxes(self) -> dict[str, float | None]:
        # This method is required by the PlanRepository interface
        return {
            "squat": 100.0,
            "bench": 80.0,
            "deadlift": 120.0,
            "ohp": 60.0,
        }

    def save_full_plan(self, plan_dict: dict) -> int:
        # This method is required by the PlanRepository interface
        self.saved_plans.append(plan_dict)
        return 1 # Return a dummy plan ID

    def get_assistance_pool_for(self, main_lift_id: int) -> list[int]:
        # Mimic the old behavior for fetching assistance exercises
        self.assist_calls.append(main_lift_id)
        return [100 + main_lift_id, 200 + main_lift_id, 300 + main_lift_id]

    def get_core_pool_ids(self) -> list[int]:
        # Mimic the old behavior for fetching core exercises
        return [999, 998, 997]


@pytest.fixture
def repo() -> DummyRepo:
    """Fixture to provide an instance of our fake repository."""
    return DummyRepo()


def test_plan_factory_builds_correct_block_structure(repo: DummyRepo):
    """
    This test replaces the old test_block_structure.
    It now tests the PlanFactory directly, which is responsible for the business logic
    of creating the plan structure.
    """
    # The training maxes are now provided by the repository itself
    training_maxes = repo.get_latest_training_maxes()
    start_date = date(2025, 1, 6)  # a Monday

    # Instantiate the factory with our fake repository
    plan_factory = PlanFactory(plan_repository=repo)

    # Call the method that creates the plan
    plan_dict = plan_factory.create_531_block_plan(start_date, training_maxes)

    # Assertions are now made against the dictionary returned by the factory
    assert plan_dict is not None
    assert len(plan_dict["plan_weeks"]) == 4

    # Flatten all workouts from the plan for easier inspection
    all_workouts = [
        workout
        for week in plan_dict["plan_weeks"]
        for workout in week["workouts"]
    ]

    blaze_days = set(schedule_rules.BLAZE_TIMES).intersection(schedule_rules.MAIN_LIFT_BY_DOW)

    # Each training day has main sets plus assistance/core, and Blaze only when enabled for that day.
    expected_total = 0
    for week_idx in range(1, 5):
        main_sets = len(schedule_rules.get_main_set_scheme(week_idx))
        for dow in schedule_rules.MAIN_LIFT_BY_DOW:
            expected_total += main_sets + 3 + int(dow in blaze_days)
        expected_total += 3  # conservative foundation running sessions layered onto Mon/Thu/Sat
        expected_total += len(schedule_rules.TRAINING_DAY_STRETCH_ROUTINE_BY_DOW)
    assert len(all_workouts) == expected_total

    # Blaze cardio sessions should match the currently configured schedule.
    blaze_workouts = [w for w in all_workouts if w["is_cardio"] and not w.get("details")]
    assert all(w["exercise_id"] == schedule_rules.BLAZE_ID for w in blaze_workouts)
    assert len(blaze_workouts) == len(blaze_days) * 4

    stretch_workouts = [
        w
        for w in all_workouts
        if w.get("details", {}).get("session_type") == schedule_rules.STRETCH_SESSION_TYPE
    ]
    assert len(stretch_workouts) == len(schedule_rules.TRAINING_DAY_STRETCH_ROUTINE_BY_DOW) * 4
    assert all(w["type"] == schedule_rules.MOBILITY_WORKOUT_TYPE for w in stretch_workouts)

    # Verify that each main lift appears with the 5/3/1 set prescription
    for week_num in range(1, 5):
        week_workouts = plan_dict["plan_weeks"][week_num - 1]["workouts"]
        for dow, main_id in schedule_rules.MAIN_LIFT_BY_DOW.items():
            main_lifts = [
                w for w in week_workouts
                if w["day_of_week"] == dow and w["exercise_id"] == main_id
            ]
            expected_scheme = schedule_rules.get_main_set_scheme(week_num)
            assert len(main_lifts) == len(expected_scheme)
            observed_percents = [lift["percent_1rm"] for lift in main_lifts]
            expected_percents = [scheme["percent"] for scheme in expected_scheme]
            assert observed_percents == expected_percents

    # Deload week (week 4) should have reduced sets for assistance/core work
    week4_workouts = plan_dict["plan_weeks"][3]["workouts"]
    non_main_lifts_week4 = [
        w for w in week4_workouts
        if not w["is_cardio"]
        and schedule_rules.classify_exercise(w["exercise_id"]) in ("assistance", "core")
    ]
    for workout in non_main_lifts_week4:
        # Check that sets are reduced compared to the standard assistance schemes
        assert workout["sets"] < schedule_rules.ASSISTANCE_1["sets"]

    # Week 1 main lifts should have target weights derived from training maxes
    week1_main_lifts = [
        w for w in plan_dict["plan_weeks"][0]["workouts"]
        if not w["is_cardio"] and w["exercise_id"] in schedule_rules.MAIN_LIFT_BY_DOW.values()
    ]
    
    for dow, main_id in schedule_rules.MAIN_LIFT_BY_DOW.items():
        day_workouts = [
            w for w in week1_main_lifts if w["exercise_id"] == main_id and w["day_of_week"] == dow
        ]
        heaviest = max(day_workouts, key=lambda item: item["percent_1rm"])
        lift_code = schedule_rules.LIFT_CODE_BY_ID[main_id]
        tm = training_maxes[lift_code]
        summary = schedule_rules.main_set_summary(1)
        expected_weight = round((tm * summary["percent_1rm"] / 100) / 2.5) * 2.5
        assert heaviest["target_weight_kg"] == expected_weight

    week1 = plan_dict["plan_weeks"][0]["workouts"]
    week2 = plan_dict["plan_weeks"][1]["workouts"]

    monday_week1_run = next(
        w for w in week1 if w["day_of_week"] == 1 and w.get("details", {}).get("session_type") == "easy"
    )
    monday_week2_run = next(
        w for w in week2 if w["day_of_week"] == 1 and w.get("details", {}).get("session_type") == "easy"
    )
    assert monday_week1_run["exercise_id"] == schedule_rules.TREADMILL_RUN_ID
    assert monday_week2_run["exercise_id"] == schedule_rules.TREADMILL_RUN_ID

    assert any(w["day_of_week"] == 4 and w.get("details", {}).get("session_type") == "easy" for w in week1)
    assert any(w["day_of_week"] == 6 and w.get("details", {}).get("session_type") == "long_run" for w in week1)

    long_run_week1 = next(
        w for w in week1 if w["day_of_week"] == 6 and w.get("details", {}).get("session_type") == "long_run"
    )
    long_run_week2 = next(
        w for w in week2 if w["day_of_week"] == 6 and w.get("details", {}).get("session_type") == "long_run"
    )
    assert long_run_week1["details"]["steps"][0]["distance_km"] == 4
    assert long_run_week2["details"]["steps"][0]["distance_km"] == 5

    monday_stretch = next(
        w for w in week1 if w["day_of_week"] == 1 and w.get("details", {}).get("session_type") == schedule_rules.STRETCH_SESSION_TYPE
    )
    assert monday_stretch["comment"] == "Limber 11"
    assert monday_stretch["exercise_id"] is None
    assert monday_stretch["sets"] == 0
    assert monday_stretch["details"]["display_name"] == "Limber 11"
    final_step = monday_stretch["details"]["steps"][-1]
    assert final_step["name"] == "Rear-foot-elevated Hip Flexor Stretch"
    assert final_step["is_isometric"] is False
    assert final_step["includes_isometric_hold"] is True
