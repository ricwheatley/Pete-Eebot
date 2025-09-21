from datetime import date, timedelta
from typing import Any, Dict, List

import pytest

from pete_e.domain.validation import validate_and_adjust_plan


class AdherenceStubDal:
    def __init__(
        self,
        *,
        plan_start: date,
        planned_by_week: Dict[int, List[Dict[str, float]]],
        actual_by_week: Dict[int, List[Dict[str, float]]],
        recent_hr: float = 50.0,
        recent_sleep: float = 480.0,
        baseline_hr: float = 50.0,
        baseline_sleep: float = 480.0,
    ) -> None:
        self._plan_start = plan_start
        self._plan_id = 101
        self._planned_by_week = planned_by_week
        self._actual_by_week = actual_by_week
        self._recent_hr = recent_hr
        self._recent_sleep = recent_sleep
        self._baseline_hr = baseline_hr
        self._baseline_sleep = baseline_sleep
        self.backoff_calls: List[Dict[str, Any]] = []

    def get_active_plan(self) -> Dict[str, Any]:
        return {
            "id": self._plan_id,
            "start_date": self._plan_start,
            "weeks": 12,
        }

    def get_plan_muscle_volume(self, plan_id: int, week_number: int) -> List[Dict[str, float]]:
        assert plan_id == self._plan_id
        return list(self._planned_by_week.get(week_number, []))

    def get_actual_muscle_volume(self, start_date: date, end_date: date) -> List[Dict[str, float]]:
        week_index = ((start_date - self._plan_start).days // 7) + 1
        return list(self._actual_by_week.get(week_index, []))

    def get_historical_data(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        current = start_date
        while current <= end_date:
            if current >= end_date - timedelta(days=6):
                hr = self._recent_hr
                sleep = self._recent_sleep
            else:
                hr = self._baseline_hr
                sleep = self._baseline_sleep
            rows.append({
                "date": current,
                "hr_resting": hr,
                "sleep_total_minutes": sleep,
            })
            current += timedelta(days=1)
        return rows

    def apply_plan_backoff(self, week_start_date: date, set_multiplier: float, rir_increment: int) -> None:
        self.backoff_calls.append({
            "week_start": week_start_date,
            "set_multiplier": set_multiplier,
            "rir_increment": rir_increment,
        })


@pytest.fixture
def plan_start() -> date:
    return date(2025, 9, 1)


def test_low_adherence_reduces_volume(plan_start: date) -> None:
    planned = {
        2: [
            {"muscle_id": 101, "target_volume_kg": 120.0},
            {"muscle_id": 102, "target_volume_kg": 140.0},
        ]
    }
    actual = {
        2: [
            {"muscle_id": 101, "actual_volume_kg": 60.0},
            {"muscle_id": 102, "actual_volume_kg": 80.0},
        ]
    }
    dal = AdherenceStubDal(
        plan_start=plan_start,
        planned_by_week=planned,
        actual_by_week=actual,
    )
    week_start = plan_start + timedelta(days=14)

    decision = validate_and_adjust_plan(dal, week_start)

    assert decision.recommendation.set_multiplier == pytest.approx(0.90, rel=1e-3)
    assert decision.applied is True
    assert dal.backoff_calls and dal.backoff_calls[0]["set_multiplier"] == pytest.approx(0.90, rel=1e-3)
    assert any("adherence_direction=reduce" in entry for entry in decision.log_entries)
    adherence_metrics = decision.recommendation.metrics.get("adherence")
    assert adherence_metrics and adherence_metrics.get("applied_direction") == "reduce"


def test_high_adherence_increases_volume_when_recovery_good(plan_start: date) -> None:
    planned = {
        2: [
            {"muscle_id": 201, "target_volume_kg": 100.0},
            {"muscle_id": 202, "target_volume_kg": 80.0},
        ]
    }
    actual = {
        2: [
            {"muscle_id": 201, "actual_volume_kg": 130.0},
            {"muscle_id": 202, "actual_volume_kg": 95.0},
        ]
    }
    dal = AdherenceStubDal(
        plan_start=plan_start,
        planned_by_week=planned,
        actual_by_week=actual,
    )
    week_start = plan_start + timedelta(days=14)

    decision = validate_and_adjust_plan(dal, week_start)

    assert decision.recommendation.set_multiplier == pytest.approx(1.05, rel=1e-3)
    assert decision.applied is True
    assert dal.backoff_calls and dal.backoff_calls[0]["set_multiplier"] == pytest.approx(1.05, rel=1e-3)
    assert any("adherence_direction=increase" in entry for entry in decision.log_entries)
    adherence_metrics = decision.recommendation.metrics.get("adherence")
    assert adherence_metrics and adherence_metrics.get("applied_direction") == "increase"


def test_high_adherence_blocked_when_recovery_flagged(plan_start: date) -> None:
    planned = {
        2: [
            {"muscle_id": 301, "target_volume_kg": 110.0},
            {"muscle_id": 302, "target_volume_kg": 90.0},
        ]
    }
    actual = {
        2: [
            {"muscle_id": 301, "actual_volume_kg": 130.0},
            {"muscle_id": 302, "actual_volume_kg": 110.0},
        ]
    }
    dal = AdherenceStubDal(
        plan_start=plan_start,
        planned_by_week=planned,
        actual_by_week=actual,
        recent_hr=55.0,
    )
    week_start = plan_start + timedelta(days=14)

    decision = validate_and_adjust_plan(dal, week_start)

    assert decision.recommendation.set_multiplier == pytest.approx(0.90, rel=1e-3)
    assert any("adherence_gated_by=recovery" in entry for entry in decision.log_entries)
    adherence_metrics = decision.recommendation.metrics.get("adherence")
    assert adherence_metrics and adherence_metrics.get("gated_by_recovery") is True
    assert adherence_metrics.get("applied_direction") != "increase"
