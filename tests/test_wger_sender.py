from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Tuple

import pytest

from pete_e.application import wger_sender
from pete_e.domain.validation import (
    BackoffRecommendation,
    ReadinessSummary,
    ValidationDecision,
)


class FakeDal:
    def __init__(self, exported: bool = False) -> None:
        self._exported = exported
        self.recorded: List[Tuple[int, int, Dict[str, Any], Dict[str, Any] | None, int | None]] = []

    def was_week_exported(self, plan_id: int, week: int) -> bool:
        return self._exported

    def record_wger_export(
        self,
        plan_id: int,
        week_number: int,
        payload: Dict[str, Any],
        response: Dict[str, Any] | None = None,
        routine_id: int | None = None,
    ) -> None:
        self.recorded.append((plan_id, week_number, payload, response, routine_id))


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
        lambda dal, start_date: {"ratio": 0.75, "actual_total": 900.0, "planned_total": 1200.0},
        raising=False,
    )


def test_push_week_exports_through_unified_path(monkeypatch):
    logs: List[Tuple[str, str]] = []

    def fake_log(msg: str, level: str = "INFO") -> None:
        logs.append((level, msg))

    built_payloads: List[Tuple[int, int]] = []

    def fake_payload(plan_id: int, week_number: int) -> Dict[str, Any]:
        built_payloads.append((plan_id, week_number))
        return {"plan_id": plan_id, "week_number": week_number, "days": []}

    exports: List[Dict[str, Any]] = []

    def fake_export(payload: Dict[str, Any], week_start: date, week_end: date | None = None) -> Dict[str, Any]:
        exports.append({"payload": payload, "week_start": week_start, "week_end": week_end})
        return {"routine_id": 77}

    monkeypatch.setattr(wger_sender.log_utils, "log_message", fake_log, raising=False)
    monkeypatch.setattr(wger_sender, "build_week_payload", fake_payload, raising=False)
    monkeypatch.setattr(wger_sender, "export_week_to_wger", fake_export, raising=False)

    dal = FakeDal(exported=False)
    result = wger_sender.push_week(dal, plan_id=42, week=2, start_date=date(2025, 1, 6))

    assert result["status"] == "exported"
    assert built_payloads == [(42, 2)]
    assert exports and exports[0]["week_start"] == date(2025, 1, 6)
    assert dal.recorded and dal.recorded[0][0:2] == (42, 2)
    assert any("Adjustments: severity=none" in msg for _, msg in logs)
    assert any("Adherence ratio 0.75" in msg for _, msg in logs)


def test_push_week_skips_if_already_exported(monkeypatch):
    logs: List[Tuple[str, str]] = []

    def fake_log(msg: str, level: str = "INFO") -> None:
        logs.append((level, msg))

    def fail_payload(*_args, **_kwargs):  # pragma: no cover - ensures skip path short-circuits
        raise AssertionError("build_week_payload should not be called when export already exists")

    monkeypatch.setattr(wger_sender.log_utils, "log_message", fake_log, raising=False)
    monkeypatch.setattr(wger_sender, "build_week_payload", fail_payload, raising=False)

    dal = FakeDal(exported=True)
    result = wger_sender.push_week(dal, plan_id=99, week=3, start_date=date(2024, 12, 2))

    assert result == {"status": "skipped", "reason": "already-exported"}
    assert not dal.recorded
    assert any("skipping push" in msg for _, msg in logs)
    assert any("Adherence ratio 0.75" in msg for _, msg in logs)
