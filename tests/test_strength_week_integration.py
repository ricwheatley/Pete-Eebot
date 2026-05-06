from __future__ import annotations

from datetime import date

from pete_e.domain import schedule_rules
from pete_e.domain.plan_factory import PlanFactory
from pete_e.domain.repositories import PlanRepository


class StaticRepository(PlanRepository):
    def get_assistance_pool_for(self, main_lift_id: int):
        return []
        """Perform get assistance pool for."""

    def get_core_pool_ids(self):
        return [800]
        """Perform get core pool ids."""

    def get_latest_training_maxes(self):
        return {}
        """Perform get latest training maxes."""

    def save_full_plan(self, plan_dict):
        return 0
        """Perform save full plan."""
    """Represent StaticRepository."""


def test_531_block_plan_includes_blaze_sessions(monkeypatch):
    monkeypatch.setattr("random.sample", lambda population, k: population[:k])

    factory = PlanFactory(plan_repository=StaticRepository())
    plan = factory.create_531_block_plan(start_date=date(2024, 6, 3), training_maxes={})

    first_week = plan["plan_weeks"][0]
    blaze_entries = [
        entry for entry in first_week["workouts"] if entry.get("is_cardio") and not entry.get("details")
    ]
    expected_blaze_days = set(schedule_rules.BLAZE_TIMES).intersection(
        schedule_rules.MAIN_LIFT_BY_DOW
    )

    assert len(blaze_entries) == len(expected_blaze_days)
    assert all(entry["exercise_id"] == schedule_rules.BLAZE_ID for entry in blaze_entries)
    """Perform test 531 block plan includes blaze sessions."""


def test_531_block_plan_includes_core_work(monkeypatch):
    monkeypatch.setattr("random.sample", lambda population, k: population[:k])

    factory = PlanFactory(plan_repository=StaticRepository())
    plan = factory.create_531_block_plan(start_date=date(2024, 6, 3), training_maxes={})

    first_week = plan["plan_weeks"][0]
    core_entries = [entry for entry in first_week["workouts"] if entry.get("exercise_id") == 800]
    assert core_entries
    """Perform test 531 block plan includes core work."""
