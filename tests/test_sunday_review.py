from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import pytest

from pete_e.application import orchestrator as orchestrator_module
from pete_e.application.orchestrator import Orchestrator
from pete_e.domain.validation import (
    BackoffRecommendation,
    ReadinessSummary,
    ValidationDecision,
)
from tests.mock_dal import MockableDal


class SundayReviewDal(MockableDal):
    def __init__(self, cycle: Dict[str, Any]) -> None:
        super().__init__()
        self._cycle = dict(cycle)
        self.updated: List[Dict[str, Any]] = []
        self.plans: Dict[date, Dict[str, Any]] = {}

    def get_active_training_cycle(self) -> Optional[Dict[str, Any]]:
        return dict(self._cycle)

    def update_training_cycle_state(
        self,
        cycle_id: int,
        *,
        current_week: int,
        current_block: int,
    ) -> Optional[Dict[str, Any]]:
        self._cycle["current_week"] = current_week
        self._cycle["current_block"] = current_block
        snapshot = dict(self._cycle)
        self.updated.append(snapshot)
        return snapshot

    def find_plan_by_start_date(self, start_date: date) -> Optional[Dict[str, Any]]:
        plan = self.plans.get(start_date)
        if not plan:
            return None
        return dict(plan)

    def get_active_plan(self) -> Optional[Dict[str, Any]]:
        if not self.plans:
            return None
        latest_start = max(self.plans.keys())
        plan = dict(self.plans[latest_start])
        plan["start_date"] = latest_start
        return plan


def _stub_sender(messages: List[str]):
    def _send(message: str) -> bool:
        messages.append(message)
        return True

    return _send


def test_run_sunday_review_evaluates_strength_test(monkeypatch: pytest.MonkeyPatch) -> None:
    start = date(2024, 1, 1)
    cycle = {"id": 7, "start_date": start, "current_week": 2, "current_block": 0}
    dal = SundayReviewDal(cycle)

    messages: List[str] = []
    exports: List[tuple[int, int, date]] = []
    evaluate_calls: Dict[str, int] = {"count": 0}

    orch = Orchestrator(dal=dal)
    monkeypatch.setattr(orch, "send_telegram_message", _stub_sender(messages), raising=False)

    def fake_evaluate(self: Orchestrator) -> Dict[str, Any]:
        evaluate_calls["count"] += 1
        return {"status": "ok"}

    def fake_generate(
        self: Orchestrator,
        *,
        start_date: date | None = None,
        training_maxes: Dict[str, float] | None = None,
        weeks: int = 4,
    ) -> int:
        assert start_date == start + timedelta(days=7)
        dal.plans[start_date] = {"id": 101, "start_date": start_date, "weeks": weeks}
        return 101

    monkeypatch.setattr(Orchestrator, "evaluate_strength_test_week", fake_evaluate, raising=False)
    monkeypatch.setattr(Orchestrator, "generate_next_block", fake_generate, raising=False)
    monkeypatch.setattr(
        orchestrator_module,
        "summarise_readiness",
        lambda *_: pytest.fail("Readiness check not expected for first block week"),
    )
    monkeypatch.setattr(
        orchestrator_module,
        "validate_and_adjust_plan",
        lambda *_: pytest.fail("Validation not expected for first block week"),
    )

    def fake_push(dal_obj: Any, plan_id: int, week: int, start_date: date) -> Dict[str, Any]:
        exports.append((plan_id, week, start_date))
        return {"status": "exported"}

    monkeypatch.setattr(orchestrator_module.wger_sender, "push_week", fake_push)

    reference = start + timedelta(days=6)  # Sunday after strength test week
    result = orch.run_sunday_review(reference_date=reference)

    assert result["status"] == "exported"
    assert evaluate_calls["count"] == 1
    assert exports == [(101, 1, start + timedelta(days=7))]
    assert dal.updated and dal.updated[-1]["current_week"] == 3
    assert dal.updated[-1]["current_block"] == 1
    assert any("Week 2" in message for message in messages)


def test_run_sunday_review_progresses_block(monkeypatch: pytest.MonkeyPatch) -> None:
    start = date(2024, 1, 1)
    cycle = {"id": 9, "start_date": start, "current_week": 6, "current_block": 1}
    dal = SundayReviewDal(cycle)

    messages: List[str] = []
    exports: List[tuple[int, int, date]] = []
    progress_called: Dict[str, date] = {}

    orch = Orchestrator(dal=dal)
    monkeypatch.setattr(orch, "send_telegram_message", _stub_sender(messages), raising=False)

    def fake_progress(self: Orchestrator, *, start_date: date | None = None) -> int:
        assert start_date == start + timedelta(days=35)
        progress_called["start_date"] = start_date
        dal.plans[start_date] = {"id": 202, "start_date": start_date, "weeks": 4}
        return 202

    monkeypatch.setattr(Orchestrator, "progress_to_next_block", fake_progress, raising=False)
    monkeypatch.setattr(
        Orchestrator,
        "generate_next_block",
        lambda *args, **kwargs: pytest.fail("Should not generate_next_block when progressing"),
        raising=False,
    )
    monkeypatch.setattr(
        orchestrator_module,
        "summarise_readiness",
        lambda *_: pytest.fail("Readiness check not expected on first week of block"),
    )
    monkeypatch.setattr(
        orchestrator_module,
        "validate_and_adjust_plan",
        lambda *_: pytest.fail("Validation not expected on first week of block"),
    )

    def fake_push(dal_obj: Any, plan_id: int, week: int, start_date: date) -> Dict[str, Any]:
        exports.append((plan_id, week, start_date))
        return {"status": "exported"}

    monkeypatch.setattr(orchestrator_module.wger_sender, "push_week", fake_push)

    reference = start + timedelta(days=34)  # Sunday after week 5
    result = orch.run_sunday_review(reference_date=reference)

    assert result["status"] == "exported"
    assert progress_called["start_date"] == start + timedelta(days=35)
    assert exports == [(202, 1, start + timedelta(days=35))]
    assert dal.updated and dal.updated[-1]["current_week"] == 7
    assert dal.updated[-1]["current_block"] == 2
    assert any("Week 6" in message for message in messages)


def test_run_sunday_review_exports_when_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    start = date(2024, 1, 1)
    plan_start = start + timedelta(days=7)
    cycle = {"id": 11, "start_date": start, "current_week": 3, "current_block": 1}
    dal = SundayReviewDal(cycle)
    dal.plans[plan_start] = {"id": 301, "start_date": plan_start, "weeks": 4}

    messages: List[str] = []
    exports: List[tuple[int, int, date]] = []

    orch = Orchestrator(dal=dal)
    monkeypatch.setattr(orch, "send_telegram_message", _stub_sender(messages), raising=False)

    readiness = ReadinessSummary(
        state="ready",
        headline="Recovery steady",
        tip=None,
        severity="none",
        breach_ratio=0.0,
        reasons=[],
    )
    recommendation = BackoffRecommendation(
        needs_backoff=False,
        severity="none",
        reasons=[],
        set_multiplier=1.0,
        rir_increment=0,
        metrics={},
    )
    decision = ValidationDecision(
        needs_backoff=False,
        applied=False,
        explanation="No adjustment required.",
        log_entries=[],
        readiness=readiness,
        recommendation=recommendation,
    )

    monkeypatch.setattr(
        orchestrator_module,
        "summarise_readiness",
        lambda *_: readiness,
    )
    monkeypatch.setattr(
        orchestrator_module,
        "validate_and_adjust_plan",
        lambda *_: decision,
    )

    def fake_push(dal_obj: Any, plan_id: int, week: int, start_date: date) -> Dict[str, Any]:
        exports.append((plan_id, week, start_date))
        return {"status": "exported"}

    monkeypatch.setattr(orchestrator_module.wger_sender, "push_week", fake_push)

    reference = start + timedelta(days=13)  # Sunday after week 2
    result = orch.run_sunday_review(reference_date=reference)

    assert result["status"] == "exported"
    assert exports == [(301, 2, start + timedelta(days=14))]
    assert dal.updated and dal.updated[-1]["current_week"] == 4
    assert dal.updated[-1]["current_block"] == 1
    assert any("kept as planned" in message for message in messages)


def test_run_sunday_review_holds_when_readiness_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    start = date(2024, 1, 1)
    plan_start = start + timedelta(days=7)
    cycle = {"id": 13, "start_date": start, "current_week": 4, "current_block": 1}
    dal = SundayReviewDal(cycle)
    dal.plans[plan_start] = {"id": 401, "start_date": plan_start, "weeks": 4}

    messages: List[str] = []

    orch = Orchestrator(dal=dal)
    monkeypatch.setattr(orch, "send_telegram_message", _stub_sender(messages), raising=False)

    readiness = ReadinessSummary(
        state="critical",
        headline="Recovery dip detected",
        tip="Take a full rest day.",
        severity="severe",
        breach_ratio=1.4,
        reasons=["HRV low"],
    )
    recommendation = BackoffRecommendation(
        needs_backoff=True,
        severity="severe",
        reasons=["HRV low"],
        set_multiplier=0.80,
        rir_increment=1,
        metrics={},
    )
    decision = ValidationDecision(
        needs_backoff=True,
        applied=True,
        explanation="Global back-off applied.",
        log_entries=["severity=severe"],
        readiness=readiness,
        recommendation=recommendation,
    )

    monkeypatch.setattr(orchestrator_module, "summarise_readiness", lambda *_: readiness)
    monkeypatch.setattr(orchestrator_module, "validate_and_adjust_plan", lambda *_: decision)
    monkeypatch.setattr(
        orchestrator_module.wger_sender,
        "push_week",
        lambda *_: pytest.fail("Plan export should be held when readiness fails"),
    )

    reference = start + timedelta(days=20)  # Sunday after week 3
    result = orch.run_sunday_review(reference_date=reference)

    assert result["status"] == "held"
    assert not dal.updated  # No progression while plan held
    assert result["hold_reason"] and "Readiness" in result["hold_reason"].title()
    assert any("Holding" in message for message in messages)


def test_run_sunday_review_scales_when_adherence_low(monkeypatch: pytest.MonkeyPatch) -> None:
    start = date(2024, 1, 1)
    plan_start = start + timedelta(days=7)
    cycle = {"id": 15, "start_date": start, "current_week": 5, "current_block": 1}
    dal = SundayReviewDal(cycle)
    dal.plans[plan_start] = {"id": 501, "start_date": plan_start, "weeks": 4}

    messages: List[str] = []
    exports: List[tuple[int, int, date]] = []

    orch = Orchestrator(dal=dal)
    monkeypatch.setattr(orch, "send_telegram_message", _stub_sender(messages), raising=False)

    readiness = ReadinessSummary(
        state="ready",
        headline="Recovery steady",
        tip=None,
        severity="none",
        breach_ratio=0.0,
        reasons=[],
    )
    recommendation = BackoffRecommendation(
        needs_backoff=False,
        severity="none",
        reasons=["Adherence below target"],
        set_multiplier=0.85,
        rir_increment=0,
        metrics={},
    )
    decision = ValidationDecision(
        needs_backoff=False,
        applied=True,
        explanation="Adherence below target; scaling sets by 0.85.",
        log_entries=["direction=reduce"],
        readiness=readiness,
        recommendation=recommendation,
    )

    monkeypatch.setattr(orchestrator_module, "summarise_readiness", lambda *_: readiness)
    monkeypatch.setattr(orchestrator_module, "validate_and_adjust_plan", lambda *_: decision)

    def fake_push(dal_obj: Any, plan_id: int, week: int, start_date: date) -> Dict[str, Any]:
        exports.append((plan_id, week, start_date))
        return {"status": "exported"}

    monkeypatch.setattr(orchestrator_module.wger_sender, "push_week", fake_push)

    reference = start + timedelta(days=27)  # Sunday after week 4
    result = orch.run_sunday_review(reference_date=reference)

    assert result["status"] == "exported"
    assert exports == [(501, 4, start + timedelta(days=28))]
    assert dal.updated and dal.updated[-1]["current_week"] == 6
    assert dal.updated[-1]["current_block"] == 1
    assert any("scaled to 85%" in message for message in messages)
    assert "validate-plan" in result["actions"]
