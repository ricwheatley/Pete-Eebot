from __future__ import annotations

from datetime import date
from typing import Any, Dict

from pete_e.application.services import PlanService


class StrengthDalStub:
    def __init__(self) -> None:
        self.saved: Dict[str, Any] = {}
        self.calls = 0

    def get_latest_training_maxes(self) -> Dict[str, float]:
        return {"bench": 120.0, "squat": 180.0, "deadlift": 220.0, "ohp": 70.0}

    def save_full_plan(self, plan_dict: Dict[str, Any]) -> int:
        self.calls += 1
        self.saved = plan_dict
        return 55


def test_create_strength_test_week_persists_plan():
    dal = StrengthDalStub()
    service = PlanService(dal=dal)

    plan_id = service.create_and_persist_strength_test_week(start_date=date(2024, 3, 4))

    assert plan_id == 55
    assert dal.calls == 1
    assert dal.saved["weeks"] == 1
    week = dal.saved["plan_weeks"][0]
    lift_entries = [entry for entry in week["workouts"] if not entry["is_cardio"]]
    assert len(lift_entries) == 4
