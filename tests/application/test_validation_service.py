from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import pytest

from pete_e.application.validation_service import ValidationService
from pete_e.domain.validation import (
    BackoffRecommendation,
    MAX_BASELINE_WINDOW_DAYS,
    PlanContext,
    ReadinessSummary,
    ValidationDecision,
    calculate_effective_prescription,
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
        self.adjustment_calls: List[Dict[str, Any]] = []
        """Initialize this object."""

    def get_historical_data(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        self.history_calls.append({"start": start_date, "end": end_date})
        return list(self._historical_rows)
        """Perform get historical data."""

    def get_active_plan(self) -> Optional[Dict[str, Any]]:
        return self._plan
        """Perform get active plan."""

    def find_plan_by_start_date(self, start_date: date) -> Optional[Dict[str, Any]]:  # noqa: ARG002
        return None
        """Perform find plan by start date."""

    def get_plan_muscle_volume(self, plan_id: int, week_number: int) -> List[Dict[str, Any]]:  # noqa: ARG002
        return list(self._planned_volume)
        """Perform get plan muscle volume."""

    def get_actual_muscle_volume(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:  # noqa: ARG002
        return list(self._actual_volume)
        """Perform get actual muscle volume."""

    def get_data_for_validation(self, week_start: date) -> Dict[str, Any]:
        self.validation_calls.append({"week_start": week_start})
        return super().get_data_for_validation(week_start)
        """Perform get data for validation."""

    def apply_plan_adjustment(self, **kwargs: Any) -> Dict[str, Any]:
        self.adjustment_calls.append(dict(kwargs))
        return {"adjustment_id": 41, "created": len(self.adjustment_calls) == 1}
        """Perform apply plan adjustment."""
    """Represent StubDal."""


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
    """Perform make decision."""


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
        """Perform fake validate."""

    monkeypatch.setattr(
        "pete_e.application.validation_service.domain_assess_plan_adjustment",
        fake_validate,
    )

    service = ValidationService(dal)
    assessed = service.assess_plan(week_start)

    assert assessed.applied is False
    assert not dal.adjustment_calls

    decision = service.apply_adjustment(assessed)

    assert captured["rows"] == hist
    assert captured["week"] == week_start
    assert isinstance(captured["plan_context"], PlanContext)
    assert captured["plan_context"].plan_id == 5
    assert captured["snapshot"] and captured["snapshot"]["plan_id"] == 5
    assert dal.adjustment_calls and dal.adjustment_calls[0]["set_multiplier"] == pytest.approx(1.05)
    assert dal.adjustment_calls[0]["plan_id"] == 5
    assert dal.adjustment_calls[0]["week_number"] == 3
    assert len(dal.validation_calls) == 1
    assert decision.applied is True
    assert decision.should_apply is True
    """Perform test validation service applies adjustment."""


def test_validation_service_handles_no_application(monkeypatch: pytest.MonkeyPatch) -> None:
    hist = [{"date": date(2024, 6, 1), "hr_resting": 50.0, "sleep_total_minutes": 420.0}]
    dal = StubDal(hist, plan=None, planned_volume=[], actual_volume=[])

    monkeypatch.setattr(
        "pete_e.application.validation_service.domain_assess_plan_adjustment",
        lambda *args, **kwargs: _make_decision(should_apply=False),
    )

    service = ValidationService(dal)
    decision = service.validate_and_adjust_plan(date(2024, 6, 10))

    assert decision.applied is False
    assert not dal.adjustment_calls
    assert len(dal.validation_calls) == 1
    """Perform test validation service handles no application."""


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
        """Initialize this object."""

    def get_active_plan(self) -> Optional[Dict[str, Any]]:
        return self.plan_record
        """Perform get active plan."""

    def find_plan_by_start_date(self, start_date: date) -> Optional[Dict[str, Any]]:  # noqa: ARG002
        return None
        """Perform find plan by start date."""

    def get_historical_data(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        self.calls["history"] = (start_date, end_date)
        return list(self.history)
        """Perform get historical data."""

    def get_plan_muscle_volume(self, plan_id: int, week_number: int) -> List[Dict[str, Any]]:
        self.calls.setdefault("planned", []).append((plan_id, week_number))
        return list(self.planned_by_week.get(week_number, []))
        """Perform get plan muscle volume."""

    def get_actual_muscle_volume(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        self.calls["actual"] = (start_date, end_date)
        return list(self.actual_rows)
        """Perform get actual muscle volume."""
    """Represent ComprehensiveDal."""


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
    """Perform test mock dal get data for validation compiles expected payload."""


class IdempotentAdjustmentDal(StubDal):
    def __init__(self, historical_rows: List[Dict[str, Any]]) -> None:
        super().__init__(
            historical_rows,
            plan={"id": 5, "start_date": date(2024, 6, 10)},
            planned_volume=[],
            actual_volume=[],
        )
        self.baseline_sets = 5
        self.baseline_rir = 2.0
        self.effective_sets = self.baseline_sets
        self.effective_rir = self.baseline_rir
        self.ledger: Dict[tuple[Any, ...], int] = {}

    def get_plan_week_rows(self, plan_id: int, week_number: int) -> List[Dict[str, Any]]:
        return [
            {
                "id": 99,
                "day_of_week": 1,
                "exercise_id": 73,
                "baseline_sets": self.baseline_sets,
                "sets": self.effective_sets,
                "baseline_rir": self.baseline_rir,
                "rir": self.effective_rir,
            }
        ]

    def apply_plan_adjustment(self, **kwargs: Any) -> Dict[str, Any]:
        self.adjustment_calls.append(dict(kwargs))
        key = (
            kwargs["plan_id"],
            kwargs["week_number"],
            kwargs["policy_version"],
            kwargs["source_data_hash"],
            kwargs["baseline_prescription_hash"],
        )
        created = key not in self.ledger
        self.ledger.setdefault(key, len(self.ledger) + 1)
        effective = calculate_effective_prescription(
            baseline_sets=self.baseline_sets,
            baseline_rir=self.baseline_rir,
            set_multiplier=kwargs["set_multiplier"],
            rir_increment=kwargs["rir_increment"],
        )
        self.effective_sets = effective.sets
        self.effective_rir = effective.rir
        return {"adjustment_id": self.ledger[key], "created": created}


def _decision_with_adjustment(set_multiplier: float, rir_increment: int) -> ValidationDecision:
    decision = _make_decision(should_apply=True)
    return replace(
        decision,
        recommendation=replace(
            decision.recommendation,
            set_multiplier=set_multiplier,
            rir_increment=rir_increment,
        ),
    )


def test_identical_assessment_applications_converge_to_one_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    week_start = date(2024, 6, 10)
    dal = IdempotentAdjustmentDal(
        [{"date": date(2024, 6, 9), "hr_resting": 55.0, "mode": "backoff"}]
    )
    monkeypatch.setattr(
        "pete_e.application.validation_service.domain_assess_plan_adjustment",
        lambda *args, **kwargs: _decision_with_adjustment(0.8, 1),
    )
    service = ValidationService(dal)

    first = service.apply_adjustment(service.assess_plan(week_start))
    state_after_one = (dal.effective_sets, dal.effective_rir)
    second = service.apply_adjustment(service.assess_plan(week_start))
    state_after_two = (dal.effective_sets, dal.effective_rir)

    assert first.adjustment_id == second.adjustment_id
    assert state_after_one == state_after_two == (4, 3.0)
    assert len(dal.ledger) == 1


def test_changed_source_or_policy_creates_one_new_effective_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    week_start = date(2024, 6, 10)
    dal = IdempotentAdjustmentDal(
        [{"date": date(2024, 6, 9), "hr_resting": 55.0, "mode": "mild"}]
    )

    def fake_assess(rows, *args, **kwargs):
        mode = rows[-1]["mode"]
        return _decision_with_adjustment(0.8 if mode == "mild" else 0.6, 1 if mode == "mild" else 2)

    monkeypatch.setattr(
        "pete_e.application.validation_service.domain_assess_plan_adjustment",
        fake_assess,
    )
    service_v1 = ValidationService(dal, policy_version="policy-v1")
    first = service_v1.apply_adjustment(service_v1.assess_plan(week_start))

    dal._historical_rows[-1]["mode"] = "severe"
    changed_source = service_v1.apply_adjustment(service_v1.assess_plan(week_start))
    duplicate_source = service_v1.apply_adjustment(service_v1.assess_plan(week_start))

    service_v2 = ValidationService(dal, policy_version="policy-v2")
    changed_policy = service_v2.apply_adjustment(service_v2.assess_plan(week_start))
    duplicate_policy = service_v2.apply_adjustment(service_v2.assess_plan(week_start))

    assert first.adjustment_id != changed_source.adjustment_id
    assert changed_source.adjustment_id == duplicate_source.adjustment_id
    assert changed_policy.adjustment_id == duplicate_policy.adjustment_id
    assert changed_policy.adjustment_id not in {first.adjustment_id, changed_source.adjustment_id}
    assert (dal.effective_sets, dal.effective_rir) == (3, 4.0)
    assert len(dal.ledger) == 3
