from datetime import date, timedelta
from typing import Any, Dict, List

import pytest

from pete_e.domain.plan_builder import build_block
from pete_e.domain.validation import assess_recovery_and_backoff


class HrvTrendStubDal:
    """Stub DAL exposing just enough history for recovery assessment."""

    def __init__(self, rows: List[Dict[str, Any]]) -> None:
        self._rows = rows

    def get_historical_data(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        return [row for row in self._rows if start_date <= row["date"] <= end_date]


class PlanBuilderStubDal:
    """Stub DAL for plan builder tests."""

    def __init__(self, metrics: List[Dict[str, Any]]) -> None:
        self._metrics = metrics
        self.saved_plan: Dict[str, Any] | None = None
        self.saved_start_date: date | None = None

    def find_plan_by_start_date(self, start_date: date) -> Dict[str, Any] | None:
        return None

    def get_historical_metrics(self, days: int) -> List[Dict[str, Any]]:
        if days <= len(self._metrics):
            return self._metrics[:days]
        return list(self._metrics)

    def save_training_plan(self, plan: Dict[str, Any], start_date: date) -> int:
        self.saved_plan = plan
        self.saved_start_date = start_date
        return 404


def _hrv_row(day: date, *, rhr: float = 50.0, sleep: float = 420.0, hrv: float = 60.0) -> Dict[str, Any]:
    return {
        "date": day,
        "hr_resting": rhr,
        "sleep_total_minutes": sleep,
        "hrv_sdnn_ms": hrv,
    }


@pytest.mark.parametrize("drop_percent, expected_severity", [(0.18, True), (0.30, True)])
def test_downward_hrv_trend_triggers_backoff(drop_percent: float, expected_severity: bool) -> None:
    reference = date(2025, 9, 22)
    week_start = reference + timedelta(days=1)

    baseline_value = 64.0
    drop_value = baseline_value * (1 - drop_percent)

    rows: List[Dict[str, Any]] = []
    for offset in range(40):
        day = reference - timedelta(days=offset)
        rows.append(_hrv_row(day, hrv=baseline_value))
    for offset in range(7):
        rows[offset]["hrv_sdnn_ms"] = drop_value

    stub = HrvTrendStubDal(rows)

    rec = assess_recovery_and_backoff(stub, week_start)

    assert rec.needs_backoff is expected_severity
    assert any("hrv" in reason.lower() for reason in rec.reasons)
    assert "avg_hrv_7d" in rec.metrics
    assert rec.metrics["avg_hrv_7d"] == pytest.approx(drop_value)


def test_high_vo2_increases_conditioning_volume() -> None:
    start_date = date(2025, 10, 6)
    high_vo2 = 52.0
    metrics = [
        {
            "sleep_asleep_minutes": 450.0,
            "hr_resting": 48.0,
            "vo2_max": high_vo2,
        }
        for _ in range(14)
    ]
    dal = PlanBuilderStubDal(metrics)

    plan_id = build_block(dal, start_date)

    assert plan_id == 404
    assert dal.saved_plan is not None

    conditioning_sets = [
        workout["sets"]
        for week in dal.saved_plan["weeks"]
        for workout in week["workouts"]
        if workout["slot"] == "conditioning"
    ]

    assert conditioning_sets, "Expected conditioning workouts to be present"
    assert any(sets > 1 for sets in conditioning_sets)
