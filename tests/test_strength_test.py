from __future__ import annotations

from datetime import date

from pete_e.domain.plan_factory import PlanFactory
from pete_e.domain.repositories import PlanRepository


class MinimalRepository(PlanRepository):
    def get_assistance_pool_for(self, main_lift_id: int):
        return []

    def get_core_pool_ids(self):
        return []

    def get_latest_training_maxes(self):
        return {}

    def save_full_plan(self, plan_dict):
        return 0


def test_strength_test_plan_marks_amrap_comment():
    factory = PlanFactory(plan_repository=MinimalRepository())
    plan = factory.create_strength_test_plan(start_date=date(2024, 8, 5), training_maxes={})

    week = plan["plan_weeks"][0]
    amrap_entries = [entry for entry in week["workouts"] if entry.get("comment") == "AMRAP Test"]

    assert len(amrap_entries) == 4
