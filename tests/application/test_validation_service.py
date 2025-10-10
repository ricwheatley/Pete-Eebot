from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import pytest

import tests.config_stub  # noqa: F401

from pete_e.application.validation_service import ValidationService
from pete_e.domain.validation import (
    BackoffRecommendation,
    PlanContext,
    ReadinessSummary,
    ValidationDecision,
)


@dataclass
class StubDal:
    historical_rows: List[Dict[str, Any]]
    plan: Optional[Dict[str, Any]]
    planned_volume: List[Dict[str, Any]]
    actual_volume: List[Dict[str, Any]]

    def __post_init__(self) -> None:
        self.history_calls: List[Dict[str, Any]] = []
        self.backoff_calls: List[Dict[str, Any]] = []

    def get_historical_data(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        self.history_calls.append({"start": start_date, "end": end_date})
        return self.historical_rows

    def get_active_plan(self) -> Optional[Dict[str, Any]]:
        return self.plan

    def find_plan_by_start_date(self, start_date: date) -> Optional[Dict[str, Any]]:  # noqa: ARG002
        return None

    def get_plan_muscle_volume(self, plan_id: int, week_number: int) -> List[Dict[str, Any]]:  # noqa: ARG002
        return list(self.planned_volume)

    def get_actual_muscle_volume(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:  # noqa: ARG002
        return list(self.actual_volume)

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
