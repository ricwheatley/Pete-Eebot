from __future__ import annotations

from datetime import date
from typing import Any, Dict

from pete_e.application.services import PlanService
from pete_e.domain import schedule_rules


class StrengthDalStub:
    def __init__(self) -> None:
        self.saved: Dict[str, Any] = {}
        self.calls = 0
        """Initialize this object."""

    def get_latest_training_maxes(self) -> Dict[str, float]:
        return {"bench": 120.0, "squat": 180.0, "deadlift": 220.0, "ohp": 70.0}
        """Perform get latest training maxes."""

    def save_full_plan(self, plan_dict: Dict[str, Any]) -> int:
        self.calls += 1
        self.saved = plan_dict
        return 55
        """Perform save full plan."""
    """Represent StrengthDalStub."""


def test_create_strength_test_week_persists_plan():
    dal = StrengthDalStub()
    service = PlanService(dal=dal)

    plan_id = service.create_and_persist_strength_test_week(start_date=date(2024, 3, 4))

    assert plan_id == 55
    assert dal.calls == 1
    assert dal.saved["weeks"] == 1
    week = dal.saved["plan_weeks"][0]
    assert week["is_test"] is True
    lift_entries = [
        entry
        for entry in week["workouts"]
        if entry.get("exercise_id") in schedule_rules.MAIN_LIFT_IDS
    ]
    run_entries = [
        entry
        for entry in week["workouts"]
        if (entry.get("details") or {}).get("session_type") in schedule_rules.RUN_SESSION_TYPES
    ]
    stretch_entries = [
        entry
        for entry in week["workouts"]
        if (entry.get("details") or {}).get("session_type") == schedule_rules.STRETCH_SESSION_TYPE
    ]
    assert len(lift_entries) == 4
    assert run_entries
    assert stretch_entries
    assert all(entry["scheduled_time"] != "main" for entry in lift_entries)
    assert all(entry["scheduled_time"] in {"06:00:00", "07:05:00"} for entry in lift_entries)
    """Perform test create strength test week persists plan."""
