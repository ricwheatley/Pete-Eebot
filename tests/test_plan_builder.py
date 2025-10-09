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

    # There should be 4 weeks * 4 days * (Blaze + main + 2 assist + core) = 80 workouts
    # (The original test had a miscalculation, it should be 5 workouts per day * 4 days * 4 weeks)
    assert len(all_workouts) == 4 * 4 * 5

    # Blaze cardio sessions should always be present with the correct ID
    blaze_workouts = [w for w in all_workouts if w["is_cardio"]]
    assert all(w["exercise_id"] == schedule_rules.BLAZE_ID for w in blaze_workouts)
    assert len(blaze_workouts) == 16 # 4 days * 4 weeks

    # Verify that each main lift appears once per week on the correct day
    for week_num in range(1, 5):
        week_workouts = plan_dict["plan_weeks"][week_num - 1]["workouts"]
        for dow, main_id in schedule_rules.MAIN_LIFT_BY_DOW.items():
            main_lifts = [
                w for w in week_workouts
                if w["day_of_week"] == dow and w["exercise_id"] == main_id
            ]
            assert len(main_lifts) == 1, f"Week {week_num} dow {dow} missing main lift {main_id}"

            # Verify %1RM matches the schedule
            scheme = schedule_rules.WEEK_PCTS[week_num]
            assert main_lifts[0]["percent_1rm"] == scheme["percent_1rm"]

    # Deload week (week 4) should have reduced sets for assistance/core work
    week4_workouts = plan_dict["plan_weeks"][3]["workouts"]
    non_main_lifts_week4 = [
        w for w in week4_workouts
        if not w["is_cardio"] and w["exercise_id"] not in schedule_rules.MAIN_LIFT_BY_DOW.values()
    ]
    for workout in non_main_lifts_week4:
        # Check that sets are reduced compared to the standard assistance schemes
        assert workout["sets"] < schedule_rules.ASSISTANCE_1["sets"]

    # Week 1 main lifts should have target weights derived from training maxes
    week1_main_lifts = [
        w for w in plan_dict["plan_weeks"][0]["workouts"]
        if not w["is_cardio"] and w["exercise_id"] in schedule_rules.MAIN_LIFT_BY_DOW.values()
    ]
    
    for workout in week1_main_lifts:
        lift_code = schedule_rules.LIFT_CODE_BY_ID[workout["exercise_id"]]
        tm = training_maxes[lift_code]
        week1_pct = schedule_rules.WEEK_PCTS[1]["percent_1rm"]
        expected_weight = round((tm * week1_pct / 100) / 2.5) * 2.5
        
        assert workout["target_weight_kg"] == expected_weight