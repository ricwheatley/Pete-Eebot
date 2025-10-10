from __future__ import annotations

from datetime import date

from pete_e.domain.plan_factory import PlanFactory
from pete_e.domain.repositories import PlanRepository


class StaticRepository(PlanRepository):
    def get_assistance_pool_for(self, main_lift_id: int):
        return []

    def get_core_pool_ids(self):
        return [800]

    def get_latest_training_maxes(self):
        return {}

    def save_full_plan(self, plan_dict):
        return 0


def test_531_block_plan_includes_blaze_sessions(monkeypatch):
    monkeypatch.setattr("random.sample", lambda population, k: population[:k])

    factory = PlanFactory(plan_repository=StaticRepository())
    plan = factory.create_531_block_plan(start_date=date(2024, 6, 3), training_maxes={})

    first_week = plan["plan_weeks"][0]
    blaze_entries = [entry for entry in first_week["workouts"] if entry.get("is_cardio")]
    assert blaze_entries, "Expected Blaze cardio placeholders"


def test_531_block_plan_includes_core_work(monkeypatch):
    monkeypatch.setattr("random.sample", lambda population, k: population[:k])

    factory = PlanFactory(plan_repository=StaticRepository())
    plan = factory.create_531_block_plan(start_date=date(2024, 6, 3), training_maxes={})

    first_week = plan["plan_weeks"][0]
    core_entries = [entry for entry in first_week["workouts"] if entry.get("exercise_id") == 800]
    assert core_entries
