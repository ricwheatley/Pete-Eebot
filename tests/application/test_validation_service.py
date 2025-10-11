from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import pytest

import tests.config_stub  # noqa: F401

from pete_e.application.validation_service import ValidationService
from pete_e.domain.validation import (
    BackoffRecommendation,
    MAX_BASELINE_WINDOW_DAYS,
    PlanContext,
    ReadinessSummary,
    ValidationDecision,
)
from tests.mock_dal import MockableDal


class StubDal(MockableDal):
    def __init__(
        self,
        historical_rows: List[Dict[str, Any]],
        plan: Optional[Dict[str, Any]],
        planned_volume: List[Dict[str, Any]],
        actual_volume: List[Dict[str, Any]],
    ) -> None:
        self._historical_rows = historical_rows
        self._plan = plan
        self._planned_volume = planned_volume
        self._actual_volume = actual_volume
        self.history_calls: List[Dict[str, Any]] = []
        self.validation_calls: List[Dict[str, Any]] = []
        self.backoff_calls: List[Dict[str, Any]] = []

    def get_historical_data(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        self.history_calls.append({"start": start_date, "end": end_date})
        return list(self._historical_rows)

    def get_active_plan(self) -> Optional[Dict[str, Any]]:
        return self._plan

    def find_plan_by_start_date(self, start_date: date) -> Optional[Dict[str, Any]]:  # noqa: ARG002
        return None

    def get_plan_muscle_volume(self, plan_id: int, week_number: int) -> List[Dict[str, Any]]:  # noqa: ARG002
        return list(self._planned_volume)

    def get_actual_muscle_volume(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:  # noqa: ARG002
        return list(self._actual_volume)

    def get_data_for_validation(self, week_start: date) -> Dict[str, Any]:
        self.validation_calls.append({"week_start": week_start})
        return super().get_data_for_validation(week_start)

    def apply_plan_backoff(self, week_start_date: date, *, set_multiplier: float, rir_increment: int) -> None:
        self.backoff_calls.append(
            {
                "week_start": week_start_date,
                "set_multiplier": set_multiplier,
                "rir_increment": rir_increment,
            }
        )


def _make_decision(should_apply: bool) -> ValidationDecision:
    recommendation = BackoffRecommendation(
        needs_backoff=False,
        severity="none",
        reasons=[],
        set_multiplier=1.05,
        rir_increment=1,
        metrics={"adherence": {"available": True}},
    )
    readiness = ReadinessSummary(
        state="ready",
        headline="Ready",
        tip=None,
        severity="none",
        breach_ratio=0.0,
        reasons=[],
    )
    return ValidationDecision(
        needs_backoff=False,
        should_apply=should_apply,
        explanation="ok",
        log_entries=["entry"],
        readiness=readiness,
        recommendation=recommendation,
        applied=False,
    )


def test_validation_service_applies_adjustment(monkeypatch: pytest.MonkeyPatch) -> None:
    week_start = date(2024, 6, 10)
    hist = [
        {"date": week_start - timedelta(days=idx + 1), "hr_resting": 50.0, "sleep_total_minutes": 420.0}
        for idx in range(180)
    ]
    plan = {"id": 5, "start_date": date(2024, 5, 27)}
    planned = [
        {"muscle_id": 1, "target_volume_kg": 100.0},
        {"muscle_id": 2, "target_volume_kg": 120.0},
    ]
    actual = [
        {"muscle_id": 1, "actual_volume_kg": 90.0},
        {"muscle_id": 2, "actual_volume_kg": 115.0},
    ]
    dal = StubDal(hist, plan, planned, actual)

    captured: Dict[str, Any] = {}

    def fake_validate(
        historical_rows,
        target_week,
        *,
        plan_context=None,
        adherence_snapshot=None,
    ):
        captured.update(
            {
                "rows": historical_rows,
                "week": target_week,
                "plan_context": plan_context,
                "snapshot": adherence_snapshot,
            }
        )
        return _make_decision(should_apply=True)

    monkeypatch.setattr(
        "pete_e.application.validation_service.domain_validate_and_adjust",
        fake_validate,
    )

    service = ValidationService(dal)
    decision = service.validate_and_adjust_plan(week_start)

    assert captured["rows"] == hist
    assert captured["week"] == week_start
    assert isinstance(captured["plan_context"], PlanContext)
    assert captured["plan_context"].plan_id == 5
    assert captured["snapshot"] and captured["snapshot"]["plan_id"] == 5
    assert dal.backoff_calls and dal.backoff_calls[0]["set_multiplier"] == pytest.approx(1.05)
    assert len(dal.validation_calls) == 1
    assert decision.applied is True
    assert decision.should_apply is True


def test_validation_service_handles_no_application(monkeypatch: pytest.MonkeyPatch) -> None:
    hist = [{"date": date(2024, 6, 1), "hr_resting": 50.0, "sleep_total_minutes": 420.0}]
    dal = StubDal(hist, plan=None, planned_volume=[], actual_volume=[])

    monkeypatch.setattr(
        "pete_e.application.validation_service.domain_validate_and_adjust",
        lambda *args, **kwargs: _make_decision(should_apply=False),
    )

    service = ValidationService(dal)
    decision = service.validate_and_adjust_plan(date(2024, 6, 10))

    assert decision.applied is False
    assert not dal.backoff_calls
    assert len(dal.validation_calls) == 1


class ComprehensiveDal(MockableDal):
    def __init__(self) -> None:
        self.plan_record = {"id": 9, "start_date": date(2024, 5, 27), "weeks": 4, "is_active": True}
        self.history: List[Dict[str, Any]] = [
            {"date": date(2024, 6, 8), "hr_resting": 48.0},
            {"date": date(2024, 6, 9), "hr_resting": 49.0},
        ]
        self.planned_by_week: Dict[int, List[Dict[str, Any]]] = {
            2: [{"muscle_id": 1, "target_volume_kg": 200.0}]
        }
        self.actual_rows: List[Dict[str, Any]] = [
            {"muscle_id": 1, "date": date(2024, 6, 5), "actual_volume_kg": 180.0}
        ]
        self.calls: Dict[str, Any] = {}

    def get_active_plan(self) -> Optional[Dict[str, Any]]:
        return self.plan_record

    def find_plan_by_start_date(self, start_date: date) -> Optional[Dict[str, Any]]:  # noqa: ARG002
        return None

    def get_historical_data(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        self.calls["history"] = (start_date, end_date)
        return list(self.history)

    def get_plan_muscle_volume(self, plan_id: int, week_number: int) -> List[Dict[str, Any]]:
        self.calls.setdefault("planned", []).append((plan_id, week_number))
        return list(self.planned_by_week.get(week_number, []))

    def get_actual_muscle_volume(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        self.calls["actual"] = (start_date, end_date)
        return list(self.actual_rows)


def test_mock_dal_get_data_for_validation_compiles_expected_payload() -> None:
    week_start = date(2024, 6, 10)
    dal = ComprehensiveDal()

    payload = dal.get_data_for_validation(week_start)

    assert payload["plan"] is not None
    assert payload["plan"]["plan_id"] == dal.plan_record["id"]
    assert payload["plan"]["upcoming_week_number"] == 3
    assert payload["plan"]["prior_week_number"] == 2
    assert payload["historical_rows"] == dal.history
    assert payload["planned_rows"] == dal.planned_by_week[2]
    assert payload["actual_rows"] == dal.actual_rows

    base_start = week_start - timedelta(days=1)
    base_start = base_start - timedelta(days=MAX_BASELINE_WINDOW_DAYS - 1)
    assert dal.calls["history"] == (base_start, week_start - timedelta(days=1))
    assert dal.calls["planned"] == [(dal.plan_record["id"], 2)]
    assert dal.calls["actual"] == (week_start - timedelta(days=7), week_start - timedelta(days=1))
