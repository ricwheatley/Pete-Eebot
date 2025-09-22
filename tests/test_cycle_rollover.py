from __future__ import annotations

import sys
from pathlib import Path
from datetime import date
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
        return plan_id

    def refresh_plan_view(self) -> None:
        self.refresh_calls += 1

    def find_plan_by_start_date(self, start_date: date):
        return self._plans_by_start.get(start_date)

    def get_active_plan(self):
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
