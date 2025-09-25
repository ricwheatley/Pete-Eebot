from __future__ import annotations

import sys
from pathlib import Path
from datetime import date, timedelta
from typing import Dict, Tuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pete_e.application import orchestrator as orchestrator_module
from pete_e.application.orchestrator import Orchestrator
from pete_e.application import wger_sender
from pete_e.domain import narrative_builder
from pete_e.domain.validation import (
    BackoffRecommendation,
    ReadinessSummary,
    ValidationDecision,
)
from pete_e.infrastructure import postgres_dal as postgres_module


class FakeDal:
    def __init__(self) -> None:
        self._plans_by_start: Dict[date, Dict[str, object]] = {}
        self._exports: Dict[Tuple[int, int], Dict[str, object]] = {}
        self.saved_plan_calls = 0
        self.refresh_calls = 0
        self._active_plan_id: int | None = None
        self.active_plan_calls: list[int] = []

    # --- Plan generation -------------------------------------------------
    def get_historical_metrics(self, days: int):
        return [
            {"hr_resting": 52, "sleep_asleep_minutes": 420},
            {"hr_resting": 53, "sleep_asleep_minutes": 430},
        ]

    def save_training_plan(self, plan: dict, start_date: date) -> int:
        self.saved_plan_calls += 1
        plan_id = len(self._plans_by_start) + 1
        self._plans_by_start[start_date] = {
            "id": plan_id,
            "start_date": start_date,
            "weeks": len(plan.get("weeks", [])) or 4,
        }
        if self._active_plan_id is None:
            self._active_plan_id = plan_id
        return plan_id

    def mark_plan_active(self, plan_id: int) -> None:
        self._active_plan_id = plan_id
        self.active_plan_calls.append(plan_id)

    def has_any_plan(self) -> bool:
        return bool(self._plans_by_start)

    def refresh_plan_view(self) -> None:
        self.refresh_calls += 1

    def find_plan_by_start_date(self, start_date: date):
        return self._plans_by_start.get(start_date)

    def get_plan_week(self, plan_id: int, week_number: int):
        return []

    def update_workout_targets(self, updates):
        return None

    def get_active_plan(self):
        if self._active_plan_id is not None:
            for entry in self._plans_by_start.values():
                if entry["id"] == self._active_plan_id:
                    return {
                        "id": entry["id"],
                        "start_date": entry["start_date"],
                        "weeks": entry["weeks"],
                    }
        if not self._plans_by_start:
            return None
        latest_start = max(self._plans_by_start.keys())
        entry = self._plans_by_start[latest_start]
        return {
            "id": entry["id"],
            "start_date": entry["start_date"],
            "weeks": entry["weeks"],
        }

    # --- Wger export idempotency ----------------------------------------
    def was_week_exported(self, plan_id: int, week_number: int) -> bool:
        return (plan_id, week_number) in self._exports

    def record_wger_export(self, plan_id: int, week_number: int, payload: dict, response: dict | None = None, routine_id: int | None = None) -> None:
        self._exports[(plan_id, week_number)] = {
            "payload": payload,
            "response": response,
            "routine_id": routine_id,
        }


@pytest.fixture(autouse=True)
def stub_telegram(monkeypatch, request):
    messages = []
    monkeypatch.setattr(
        orchestrator_module.telegram_sender,
        "send_message",
        lambda msg: messages.append(msg),
        raising=False,
    )
    monkeypatch.setattr(narrative_builder.PeteVoice, "nudge", lambda tag, sprinkles=None: f"Nudge {tag}")
    request.addfinalizer(postgres_module.close_pool)
    return messages


@pytest.fixture(autouse=True)
def stub_training_max(monkeypatch):
    monkeypatch.setattr(
        orchestrator_module.plan_rw,
        "latest_training_max",
        lambda: {"bench": 100.0, "squat": 150.0},
        raising=False,
    )
    monkeypatch.setattr(
        orchestrator_module.plan_rw,
        "latest_training_max_date",
        lambda: None,
        raising=False,
    )


@pytest.fixture(autouse=True)
def stub_validation(monkeypatch):
    def fake_validate(dal, start_date):
        readiness = ReadinessSummary(
            state="steady",
            headline="Steady",
            tip=None,
            severity="low",
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
            explanation="Recovery steady.",
            log_entries=["severity=none"],
            readiness=readiness,
            recommendation=recommendation,
        )

    monkeypatch.setattr(wger_sender, "validate_and_adjust_plan", fake_validate, raising=False)
    monkeypatch.setattr(
        wger_sender,
        "collect_adherence_snapshot",
        lambda dal, start_date: {
            "ratio": 0.9,
            "actual_total": 1000.0,
            "planned_total": 1100.0,
        },
        raising=False,
    )


def test_cycle_rollover_creates_plan_and_exports(monkeypatch, stub_telegram):
    exports = []

    def fake_payload(plan_id: int, week_number: int) -> dict:
        return {"plan_id": plan_id, "week_number": week_number, "days": []}

    def fake_export(payload: dict, week_start: date, week_end: date | None = None):
        exports.append({"payload": payload, "week_start": week_start, "week_end": week_end})
        return {"routine_id": 99}

    monkeypatch.setattr(wger_sender, "build_week_payload", fake_payload, raising=False)
    monkeypatch.setattr(wger_sender, "export_week_to_wger", fake_export, raising=False)

    dal = FakeDal()
    orch = Orchestrator(dal=dal)

    reference = date(2025, 9, 21)  # Sunday
    result = orch.run_cycle_rollover(reference_date=reference)

    assert result.plan_id == 1
    assert result.created is True
    assert result.exported is True
    assert exports[0]["week_start"] == date(2025, 9, 22)
    assert stub_telegram, "Expected a Telegram nudge to be sent"
    assert dal.saved_plan_calls == 1
    assert (1, 1) in dal._exports


def test_cycle_rollover_is_idempotent(monkeypatch, stub_telegram):
    exports = []

    def fake_payload(plan_id: int, week_number: int) -> dict:
        return {"plan_id": plan_id, "week_number": week_number, "days": []}

    def fake_export(payload: dict, week_start: date, week_end: date | None = None):
        exports.append({"payload": payload, "week_start": week_start, "week_end": week_end})
        return {"routine_id": 99}

    monkeypatch.setattr(wger_sender, "build_week_payload", fake_payload, raising=False)
    monkeypatch.setattr(wger_sender, "export_week_to_wger", fake_export, raising=False)

    dal = FakeDal()
    orch = Orchestrator(dal=dal)
    reference = date(2025, 9, 21)

    first = orch.run_cycle_rollover(reference_date=reference)
    second = orch.run_cycle_rollover(reference_date=reference)

    assert first.created is True and first.exported is True
    assert second.created is False
    assert second.exported is False
    assert len(exports) == 1
    assert len(stub_telegram) == 1  # no duplicate notifications
    assert dal.saved_plan_calls == 1


def test_generate_plan_rejects_unsupported_length(monkeypatch):
    build_calls: list[tuple[object, ...]] = []

    def fake_build(*args, **kwargs):  # pragma: no cover - should not be invoked
        build_calls.append((args, kwargs))
        return 42

    monkeypatch.setattr(orchestrator_module, "build_block", fake_build)

    class RejectDal:
        def __init__(self) -> None:
            self.refresh_called = False

        def refresh_plan_view(self) -> None:  # pragma: no cover - should not run
            self.refresh_called = True

    orch = Orchestrator(dal=RejectDal())
    result = orch.generate_and_deploy_next_plan(start_date=date(2025, 1, 6), weeks=6)

    assert result == -1
    assert build_calls == []
    assert orch.dal.refresh_called is False


def test_cycle_rollover_rejects_unsupported_length(monkeypatch, stub_telegram):
    build_calls: list[tuple[object, ...]] = []

    def fake_build(*args, **kwargs):  # pragma: no cover - should not be invoked
        build_calls.append((args, kwargs))
        return 42

    monkeypatch.setattr(orchestrator_module, "build_block", fake_build)

    dal = FakeDal()
    orch = Orchestrator(dal=dal)
    reference = date(2025, 9, 21)

    result = orch.run_cycle_rollover(reference_date=reference, weeks=6)

    assert result.plan_id is None
    assert result.created is False
    assert result.exported is False
    assert build_calls == []
    assert dal.saved_plan_calls == 0
    assert stub_telegram == []


def test_first_plan_uses_strength_test(monkeypatch):
    start = date(2025, 1, 6)
    dal = FakeDal()

    strength_calls: list[tuple[object, object]] = []
    export_calls: list[tuple[int, int, date]] = []

    def fake_build_strength(dal_arg, start_date):
        strength_calls.append((dal_arg, start_date))
        plan_id = dal_arg.save_training_plan({"weeks": [{"week_number": 1, "workouts": []}]}, start_date)
        return plan_id

    monkeypatch.setattr(orchestrator_module, "build_strength_test", fake_build_strength, raising=False)
    monkeypatch.setattr(orchestrator_module.plan_rw, "latest_training_max", lambda: {}, raising=False)
    monkeypatch.setattr(
        orchestrator_module.wger_sender,
        "push_week",
        lambda dal_arg, plan_id, week, start_date: export_calls.append((plan_id, week, start_date))
        or {"status": "exported"},
        raising=False,
    )

    orch = Orchestrator(dal=dal)
    plan_id = orch.generate_and_deploy_next_plan(start_date=start, weeks=4)

    assert strength_calls == [(dal, start)]
    assert plan_id == 1
    assert dal.active_plan_calls == [plan_id]
    assert export_calls == [(plan_id, 1, start)]


def test_strength_test_every_thirteen_weeks(monkeypatch):
    start = date(2025, 1, 6)
    dal = FakeDal()

    state = {"last_test_date": start - timedelta(weeks=13)}
    strength_calls: list[date] = []
    block_calls: list[date] = []
    push_calls: list[tuple[int, int, date]] = []

    def fake_latest_tm_date():
        return state["last_test_date"]

    def fake_build_strength(dal_arg, start_date):
        strength_calls.append(start_date)
        plan_id = dal_arg.save_training_plan(
            {"weeks": [{"week_number": 1, "workouts": []}]},
            start_date,
        )
        state["last_test_date"] = start_date
        return plan_id

    def fake_build_block(dal_arg, start_date, weeks: int = 4):
        block_calls.append(start_date)
        plan = {
            "weeks": [
                {"week_number": i + 1, "workouts": []}
                for i in range(weeks)
            ]
        }
        return dal_arg.save_training_plan(plan, start_date)

    def fake_push_week(dal_arg, plan_id, week, start_date):
        push_calls.append((plan_id, week, start_date))
        return {"status": "exported"}

    monkeypatch.setattr(
        orchestrator_module.plan_rw,
        "latest_training_max_date",
        fake_latest_tm_date,
        raising=False,
    )
    monkeypatch.setattr(
        orchestrator_module,
        "build_strength_test",
        fake_build_strength,
        raising=False,
    )
    monkeypatch.setattr(
        orchestrator_module,
        "build_block",
        fake_build_block,
        raising=False,
    )
    monkeypatch.setattr(
        orchestrator_module.wger_sender,
        "push_week",
        fake_push_week,
        raising=False,
    )

    orch = Orchestrator(dal=dal)

    plan_ids = [
        orch.generate_and_deploy_next_plan(start_date=start, weeks=4),
        orch.generate_and_deploy_next_plan(start_date=start + timedelta(weeks=1), weeks=4),
        orch.generate_and_deploy_next_plan(start_date=start + timedelta(weeks=5), weeks=4),
        orch.generate_and_deploy_next_plan(start_date=start + timedelta(weeks=9), weeks=4),
        orch.generate_and_deploy_next_plan(start_date=start + timedelta(weeks=13), weeks=4),
        orch.generate_and_deploy_next_plan(start_date=start + timedelta(weeks=14), weeks=4),
    ]

    assert all(pid > 0 for pid in plan_ids)
    assert strength_calls == [
        start,
        start + timedelta(weeks=13),
    ]
    assert block_calls == [
        start + timedelta(weeks=1),
        start + timedelta(weeks=5),
        start + timedelta(weeks=9),
        start + timedelta(weeks=14),
    ]
    assert [call[2] for call in push_calls] == strength_calls
