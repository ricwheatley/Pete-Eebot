from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

import pytest

import tests.config_stub  # noqa: F401

from pete_e.application.services import PlanService
from pete_e.application.strength_test import StrengthTestService
from pete_e.domain import schedule_rules


def _expected_tm(weight_kg: float, reps: int) -> float:
    e1rm = weight_kg * (1.0 + reps / 30.0)
    return round((e1rm * 0.90) / 2.5) * 2.5
    """Perform expected tm."""


class StrengthTestDal:
    def __init__(self) -> None:
        self.training_maxes: Dict[str, float] = {
            "bench": 80.0,
            "squat": 140.0,
            "ohp": 55.0,
            "deadlift": 160.0,
        }
        self.saved_plan: Dict[str, Any] = {}
        self.inserted_results: List[Dict[str, Any]] = []
        self.upserted_tms: List[tuple[str, float, date, str]] = []
        """Initialize this object."""

    def get_latest_test_week(self) -> Dict[str, Any]:
        return {
            "plan_id": 17,
            "week_number": 1,
            "start_date": date(2024, 8, 5),
        }
        """Perform get latest test week."""

    def get_plan_week_rows(self, plan_id: int, week_number: int) -> List[Dict[str, Any]]:
        assert plan_id == 17
        assert week_number == 1
        return [
            {"exercise_id": schedule_rules.BENCH_ID, "day_of_week": 1},
            {"exercise_id": schedule_rules.SQUAT_ID, "day_of_week": 2},
            {"exercise_id": schedule_rules.OHP_ID, "day_of_week": 4},
            {"exercise_id": schedule_rules.DEADLIFT_ID, "day_of_week": 5},
        ]
        """Perform get plan week rows."""

    def load_lift_log(
        self,
        exercise_ids: List[int],
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> Dict[str, Any]:
        assert set(exercise_ids) == set(schedule_rules.TEST_WEEK_LIFT_ORDER)
        assert start_date == date(2024, 8, 5)
        assert end_date == date(2024, 8, 11)
        return {
            str(schedule_rules.BENCH_ID): [
                {"date": date(2024, 8, 5), "reps": 6, "weight_kg": 92.5},
                {"date": date(2024, 8, 10), "reps": 8, "weight_kg": 92.5},
            ],
            str(schedule_rules.SQUAT_ID): [
                {"date": date(2024, 8, 6), "reps": 5, "weight_kg": 140.0},
            ],
            str(schedule_rules.OHP_ID): [
                {"date": date(2024, 8, 8), "reps": 5, "weight_kg": 60.0},
            ],
            str(schedule_rules.DEADLIFT_ID): [
                {"date": date(2024, 8, 9), "reps": 4, "weight_kg": 170.0},
            ],
        }
        """Perform load lift log."""

    def insert_strength_test_result(self, **kwargs) -> None:
        self.inserted_results.append(kwargs)
        """Perform insert strength test result."""

    def upsert_training_max(self, lift_code: str, tm_kg: float, measured_at: date, source: str) -> None:
        self.training_maxes[lift_code] = tm_kg
        self.upserted_tms.append((lift_code, tm_kg, measured_at, source))
        """Perform upsert training max."""

    def get_latest_training_maxes(self) -> Dict[str, float]:
        return dict(self.training_maxes)
        """Perform get latest training maxes."""

    def get_assistance_pool_for(self, main_lift_id: int) -> List[int]:
        return []
        """Perform get assistance pool for."""

    def get_core_pool_ids(self) -> List[int]:
        return [800]
        """Perform get core pool ids."""

    def save_full_plan(self, plan_dict: Dict[str, Any]) -> int:
        self.saved_plan = plan_dict
        return 42
        """Perform save full plan."""
    """Represent StrengthTestDal."""


def test_strength_test_service_updates_training_maxes_from_logged_amraps() -> None:
    dal = StrengthTestDal()
    service = StrengthTestService(dal)

    result = service.evaluate_latest_test_week_and_update_tms()

    assert result is not None
    assert result.plan_id == 17
    assert result.lifts_updated == 4

    bench_result = next(item for item in dal.inserted_results if item["lift_code"] == "bench")
    assert bench_result["test_date"] == date(2024, 8, 5)
    assert bench_result["tm_kg"] == pytest.approx(_expected_tm(92.5, 6))
    assert dal.training_maxes["bench"] == pytest.approx(_expected_tm(92.5, 6))
    assert all(source == "AMRAP_EPLEY" for _, _, _, source in dal.upserted_tms)
    """Perform test strength test service updates training maxes from logged amraps."""


def test_create_next_plan_for_cycle_uses_refreshed_training_maxes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("random.sample", lambda population, k: population[:k])

    dal = StrengthTestDal()
    service = PlanService(dal=dal)

    plan_id = service.create_next_plan_for_cycle(start_date=date(2024, 8, 12))

    assert plan_id == 42
    first_week = dal.saved_plan["plan_weeks"][0]
    bench_sets = [
        workout
        for workout in first_week["workouts"]
        if workout["exercise_id"] == schedule_rules.BENCH_ID
    ]
    top_set = max(bench_sets, key=lambda workout: workout["percent_1rm"])

    updated_bench_tm = _expected_tm(92.5, 6)
    expected_target = round((updated_bench_tm * top_set["percent_1rm"] / 100.0) / 2.5) * 2.5

    assert top_set["target_weight_kg"] == pytest.approx(expected_target)
    assert top_set["target_weight_kg"] > 80.0
    """Perform test create next plan for cycle uses refreshed training maxes."""
