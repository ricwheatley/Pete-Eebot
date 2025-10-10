from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

import pytest

from pete_e.application.services import PlanService
from pete_e.domain.plan_factory import PlanFactory
from pete_e.domain import schedule_rules
from pete_e.domain.repositories import PlanRepository


class StubPlanRepository(PlanRepository):
    def __init__(self) -> None:
        # map lift id -> assistance exercise ids
        self._assistance: Dict[int, List[int]] = {
            schedule_rules.SQUAT_ID: [201, 202],
            schedule_rules.BENCH_ID: [301, 302],
            schedule_rules.OHP_ID: [401, 402],
            schedule_rules.DEADLIFT_ID: [501, 502],
        }
        self._core = [900, 901]

    def get_assistance_pool_for(self, main_lift_id: int) -> List[int]:
        return list(self._assistance.get(main_lift_id, []))

    def get_core_pool_ids(self) -> List[int]:
        return list(self._core)

    def get_latest_training_maxes(self) -> Dict[str, float]:
        return _training_maxes()

    def save_full_plan(self, plan_dict: Dict[str, Any]) -> int:  # pragma: no cover - unused for factory tests
        self.saved_plan = plan_dict  # type: ignore[attr-defined]
        return 1


def _training_maxes() -> Dict[str, float]:
    return {
        "squat": 180.0,
        "bench": 120.0,
        "deadlift": 220.0,
        "ohp": 70.0,
    }


def test_plan_factory_computes_expected_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = StubPlanRepository()
    factory = PlanFactory(plan_repository=repo)
    tm = _training_maxes()

    # Make random selection deterministic
    monkeypatch.setattr("random.sample", lambda population, k: population[:k])

    plan = factory.create_531_block_plan(start_date=date(2024, 1, 1), training_maxes=tm)

    assert plan["weeks"] == 4
    first_week = plan["plan_weeks"][0]
    assert first_week["week_number"] == 1

    squat_entry = next(
        workout for workout in first_week["workouts"] if workout["exercise_id"] == schedule_rules.SQUAT_ID
    )
    percent = schedule_rules.WEEK_PCTS[1]["percent_1rm"]
    expected_weight = round((tm["squat"] * percent / 100) / 2.5) * 2.5
    assert squat_entry["target_weight_kg"] == pytest.approx(expected_weight)

    assistance_ids = [
        workout["exercise_id"]
        for workout in first_week["workouts"]
        if workout["exercise_id"] in repo._assistance[schedule_rules.SQUAT_ID]
    ]
    assert assistance_ids  # assistance movements should be present


def test_plan_service_persists_full_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    saved_payload: Dict[str, Any] = {}

    class StubDal(StubPlanRepository):
        def get_latest_training_maxes(self) -> Dict[str, float]:
            return _training_maxes()

        def save_full_plan(self, plan_dict: Dict[str, Any]) -> int:
            saved_payload.update(plan_dict)
            return 42

    service = PlanService(dal=StubDal())
    plan_id = service.create_and_persist_531_block(start_date=date(2024, 1, 1))

    assert plan_id == 42
    assert saved_payload["start_date"] == date(2024, 1, 1)
    assert saved_payload["weeks"] == 4
    assert len(saved_payload["plan_weeks"]) == 4
