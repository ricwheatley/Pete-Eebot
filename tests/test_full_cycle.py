from __future__ import annotations

from datetime import date, timedelta
import importlib
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


class FullCycleDal(MockableDal):
    def __init__(self, start_date: date) -> None:
        super().__init__()
        self._cycle: Dict[str, Any] = {
            "id": 1,
            "start_date": start_date,
            "current_week": 2,
            "current_block": 0,
        }
        self._next_cycle_id = 2
        self.plans: Dict[date, Dict[str, Any]] = {}
        self.updated: List[Dict[str, Any]] = []
        self.deactivated: List[int] = []
        self.created_cycles: List[Dict[str, Any]] = []

    def get_active_training_cycle(self) -> Optional[Dict[str, Any]]:
        if not self._cycle:
            return None
        return dict(self._cycle)

    def update_training_cycle_state(
        self,
        cycle_id: int,
        *,
        current_week: int,
        current_block: int,
    ) -> Optional[Dict[str, Any]]:
        if not self._cycle:
            return None
        self._cycle["current_week"] = current_week
        self._cycle["current_block"] = current_block
        snapshot = dict(self._cycle)
        self.updated.append(snapshot)
        return snapshot

    def deactivate_active_training_cycles(self) -> None:
        cycle_id = self._cycle.get("id") if self._cycle else None
        if cycle_id is not None:
            self.deactivated.append(int(cycle_id))
        self._cycle = {}

    def create_training_cycle(
        self,
        start_date: date,
        *,
        current_week: int,
        current_block: int,
    ) -> Dict[str, Any]:
        cycle = {
            "id": self._next_cycle_id,
            "start_date": start_date,
            "current_week": current_week,
            "current_block": current_block,
        }
        self._next_cycle_id += 1
        self.created_cycles.append(dict(cycle))
        self._cycle = dict(cycle)
        return dict(cycle)

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


def test_full_macrocycle_rollover(monkeypatch: pytest.MonkeyPatch) -> None:
    start = date(2024, 1, 1)
    dal = FullCycleDal(start)
    orch = Orchestrator(dal=dal)

    monkeypatch.setattr(orch, "send_telegram_message", lambda message: True, raising=False)

    plan_counter = {"next": 100}

    def register_plan(start_date: date) -> int:
        plan_id = plan_counter["next"]
        plan_counter["next"] += 1
        dal.plans[start_date] = {"id": plan_id, "start_date": start_date, "weeks": 4}
        return plan_id

    evaluation_calls = {"count": 0}
    generate_calls: List[date] = []
    progress_calls: List[date] = []
    readiness_calls: List[date] = []
    validation_calls: List[date] = []
    exports: List[Dict[str, Any]] = []
    strength_weeks: List[date] = []

    def fake_evaluate(self: Orchestrator) -> Dict[str, Any]:
        evaluation_calls["count"] += 1
        return {"status": "ok"}

    def fake_generate(
        self: Orchestrator,
        *,
        start_date: date | None = None,
        training_maxes: Dict[str, float] | None = None,
        weeks: int = 4,
    ) -> int:
        assert start_date is not None
        generate_calls.append(start_date)
        return register_plan(start_date)

    def fake_progress(
        self: Orchestrator,
        *,
        start_date: date | None = None,
    ) -> int:
        assert start_date is not None
        progress_calls.append(start_date)
        return register_plan(start_date)

    def fake_readiness(dal_obj: Any, week_start: date) -> ReadinessSummary:
        readiness_calls.append(week_start)
        return ReadinessSummary(
            state="ready",
            headline="On track",
            tip=None,
            severity="none",
            breach_ratio=0.0,
            reasons=[],
        )

    def fake_validate(dal_obj: Any, week_start: date) -> ValidationDecision:
        validation_calls.append(week_start)
        readiness = ReadinessSummary(
            state="ready",
            headline="On track",
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
        return ValidationDecision(
            needs_backoff=False,
            applied=False,
            explanation="",
            log_entries=[],
            readiness=readiness,
            recommendation=recommendation,
        )

    def fake_push(
        dal_obj: Any,
        plan_id: int,
        week: int,
        start_date: date,
    ) -> Dict[str, Any]:
        exports.append({"plan_id": plan_id, "week": week, "start": start_date})
        return {"status": "exported"}

    def fake_strength(self: Orchestrator, start_date: date) -> tuple[int, int] | None:
        strength_weeks.append(start_date)
        return (999, 1)

    monkeypatch.setattr(Orchestrator, "evaluate_strength_test_week", fake_evaluate, raising=False)
    monkeypatch.setattr(Orchestrator, "generate_next_block", fake_generate, raising=False)
    monkeypatch.setattr(Orchestrator, "progress_to_next_block", fake_progress, raising=False)
    monkeypatch.setattr(Orchestrator, "generate_strength_test_week", fake_strength, raising=False)
    monkeypatch.setattr(orchestrator_module, "summarise_readiness", fake_readiness)
    monkeypatch.setattr(orchestrator_module, "validate_and_adjust_plan", fake_validate)
    monkeypatch.setattr(orchestrator_module.wger_sender, "push_week", fake_push)

    results = []
    for week in range(2, 14):
        reference = start + timedelta(days=(week - 1) * 7 + 6)
        result = orch.run_sunday_review(reference_date=reference)
        results.append(result)
        assert result["status"] == "exported"
        assert result["current_week"] == week

    assert evaluation_calls["count"] == 1
    assert generate_calls == [start + timedelta(days=7)]
    assert progress_calls == [start + timedelta(days=35), start + timedelta(days=63)]
    assert len(readiness_calls) == 9
    assert len(validation_calls) == 9
    assert len(exports) == 12

    assert dal.updated[0]["current_block"] == 1
    assert any(snapshot["current_block"] == 2 for snapshot in dal.updated)
    assert any(snapshot["current_block"] == 3 for snapshot in dal.updated)

    final_result = results[-1]
    assert final_result["rollover_cycle"] is not None
    assert final_result["rollover_error"] is None

    expected_start = start + timedelta(days=13 * 7)
    assert strength_weeks == [expected_start]
    assert dal.deactivated
    assert dal.created_cycles
    assert dal.created_cycles[-1]["start_date"] == expected_start


def test_removed_scripts_are_unavailable() -> None:
    missing_modules = [
        "scripts.sprint_rollover",
        "scripts.weekly_calibration",
        "scripts.evaluate_strength_test_week",
        "scripts.schedule_strength_test_week",
    ]
    for module_name in missing_modules:
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(module_name)
