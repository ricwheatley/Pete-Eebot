from __future__ import annotations

from datetime import date

from pete_e.domain.plan_factory import PlanFactory
from pete_e.domain.repositories import PlanRepository


class StubRepository(PlanRepository):
    def get_assistance_pool_for(self, main_lift_id: int):
        return []

    def get_core_pool_ids(self):
        return []

    def get_latest_training_maxes(self):
        return {}

    def save_full_plan(self, plan_dict):
        return 0


def test_strength_test_plan_contains_all_main_lifts():
    factory = PlanFactory(plan_repository=StubRepository())
    plan = factory.create_strength_test_plan(start_date=date(2024, 2, 5), training_maxes={})

    assert plan["weeks"] == 1
    week = plan["plan_weeks"][0]
    lift_ids = {entry["exercise_id"] for entry in week["workouts"] if not entry["is_cardio"]}
    # Strength test should schedule four main lifts
    assert len(lift_ids) == 4
