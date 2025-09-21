from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pete_e.application import orchestrator as orchestrator_module
from pete_e.application.orchestrator import (
    Orchestrator,
    WeeklyCalibrationResult,
    CycleRolloverResult,
)


DAILY_SOURCES = orchestrator_module.DAILY_SYNC_SOURCES


class LedgerStub:
    def __init__(self) -> None:
        self.sent = {}

    def was_sent(self, target_date: date) -> bool:
        return target_date in self.sent

    def mark_sent(self, target_date: date, summary: str) -> None:
        self.sent[target_date] = summary


def _ok_statuses() -> dict:
    return {source: "ok" for source in DAILY_SOURCES}


def test_run_end_to_end_day_runs_ingest_and_summary(monkeypatch):
    ledger = LedgerStub()
    orch = Orchestrator(dal=object(), summary_dispatch_ledger=ledger)
    summary_date = date(2025, 9, 20)
    daily_calls: list[int] = []

    def fake_run_daily_sync(self, days: int):
        daily_calls.append(days)
        return True, [], _ok_statuses()

    monkeypatch.setattr(Orchestrator, "run_daily_sync", fake_run_daily_sync)

    summary_calls: list[date] = []

    def fake_auto(self, target_date: date) -> bool:
        summary_calls.append(target_date)
        ledger.mark_sent(target_date, "ok")
        return True

    monkeypatch.setattr(Orchestrator, "_auto_send_daily_summary", fake_auto)

    result = orch.run_end_to_end_day(days=1, summary_date=summary_date)

    assert daily_calls == [1]
    assert summary_calls == [summary_date]
    assert ledger.was_sent(summary_date)
    assert result.summary_sent is True
    assert result.ingest_success is True
    assert result.source_statuses == _ok_statuses()


def test_run_end_to_end_day_skips_summary_when_ingest_fails(monkeypatch):
    ledger = LedgerStub()
    orch = Orchestrator(dal=object(), summary_dispatch_ledger=ledger)
    summary_date = date(2025, 9, 20)

    def failing_sync(self, days: int):
        statuses = _ok_statuses()
        statuses["AppleDropbox"] = "failed"
        return False, ["AppleDropbox"], statuses

    monkeypatch.setattr(Orchestrator, "run_daily_sync", failing_sync)

    summary_calls: list[date] = []

    def fake_auto(self, target_date: date) -> bool:
        summary_calls.append(target_date)
        ledger.mark_sent(target_date, "should-not-happen")
        return True

    monkeypatch.setattr(Orchestrator, "_auto_send_daily_summary", fake_auto)

    result = orch.run_end_to_end_day(days=1, summary_date=summary_date)

    assert summary_calls == []
    assert ledger.was_sent(summary_date) is False
    assert result.summary_sent is False
    assert result.ingest_success is False
    assert result.failed_sources == ["AppleDropbox"]
    assert result.source_statuses["AppleDropbox"] == "failed"


def test_run_end_to_end_day_respects_existing_summary(monkeypatch):
    ledger = LedgerStub()
    summary_date = date(2025, 9, 20)
    ledger.mark_sent(summary_date, "existing")
    orch = Orchestrator(dal=object(), summary_dispatch_ledger=ledger)

    def ok_sync(self, days: int):
        return True, [], _ok_statuses()

    monkeypatch.setattr(Orchestrator, "run_daily_sync", ok_sync)

    summary_calls: list[date] = []

    def fake_auto(self, target_date: date) -> bool:
        summary_calls.append(target_date)
        ledger.mark_sent(target_date, "new")
        return True

    monkeypatch.setattr(Orchestrator, "_auto_send_daily_summary", fake_auto)

    result = orch.run_end_to_end_day(days=1, summary_date=summary_date)

    assert summary_calls == []
    assert ledger.sent[summary_date] == "existing"
    assert result.summary_sent is True
    assert result.ingest_success is True


def _make_calibration() -> WeeklyCalibrationResult:
    return WeeklyCalibrationResult(
        plan_id=42,
        week_number=5,
        week_start=date(2025, 9, 22),
        progression=None,
        validation=None,
        message="calibration ok",
    )


def _make_rollover() -> CycleRolloverResult:
    return CycleRolloverResult(
        plan_id=77,
        created=True,
        exported=True,
        start_date=date(2025, 10, 20),
        message="rollover ok",
    )


def test_run_end_to_end_week_skips_rollover_when_not_due(monkeypatch):
    orch = Orchestrator(dal=object())
    reference = date(2025, 9, 21)
    calibration_result = _make_calibration()
    calibration_calls: list[date | None] = []

    def fake_calibration(self, reference_date: date | None = None):
        calibration_calls.append(reference_date)
        return calibration_result

    monkeypatch.setattr(Orchestrator, "run_weekly_calibration", fake_calibration)
    monkeypatch.setattr(Orchestrator, "_should_run_cycle_rollover", lambda self, ref, cal: False)

    rollover_calls: list[tuple[date | None, int]] = []

    def fake_rollover(self, *, reference_date: date | None = None, weeks: int = 4):
        rollover_calls.append((reference_date, weeks))
        return _make_rollover()

    monkeypatch.setattr(Orchestrator, "run_cycle_rollover", fake_rollover)

    result = orch.run_end_to_end_week(reference_date=reference)

    assert calibration_calls == [reference]
    assert rollover_calls == []
    assert result.calibration is calibration_result
    assert result.rollover is None
    assert result.rollover_triggered is False


def test_run_end_to_end_week_runs_rollover_when_due(monkeypatch):
    orch = Orchestrator(dal=object())
    reference = date(2025, 9, 28)
    calibration_result = _make_calibration()
    cycle_result = _make_rollover()

    monkeypatch.setattr(Orchestrator, "run_weekly_calibration", lambda self, reference_date=None: calibration_result)
    monkeypatch.setattr(Orchestrator, "_should_run_cycle_rollover", lambda self, ref, cal: True)

    rollover_calls: list[tuple[date | None, int]] = []

    def fake_rollover(self, *, reference_date: date | None = None, weeks: int = 4):
        rollover_calls.append((reference_date, weeks))
        return cycle_result

    monkeypatch.setattr(Orchestrator, "run_cycle_rollover", fake_rollover)

    result = orch.run_end_to_end_week(reference_date=reference, rollover_weeks=6)

    assert rollover_calls == [(reference, 6)]
    assert result.calibration is calibration_result
    assert result.rollover is cycle_result
    assert result.rollover_triggered is True


def test_run_end_to_end_week_force_rollover(monkeypatch):
    orch = Orchestrator(dal=object())
    reference = date(2025, 9, 14)
    calibration_result = _make_calibration()
    cycle_result = _make_rollover()

    monkeypatch.setattr(Orchestrator, "run_weekly_calibration", lambda self, reference_date=None: calibration_result)

    should_calls: list[date] = []

    def fake_should(self, reference_date: date, calibration: WeeklyCalibrationResult) -> bool:
        should_calls.append(reference_date)
        return False

    monkeypatch.setattr(Orchestrator, "_should_run_cycle_rollover", fake_should)
    monkeypatch.setattr(Orchestrator, "run_cycle_rollover", lambda self, *, reference_date=None, weeks=4: cycle_result)

    result = orch.run_end_to_end_week(reference_date=reference, force_rollover=True)

    assert should_calls == [reference]
    assert result.calibration is calibration_result
    assert result.rollover is cycle_result
    assert result.rollover_triggered is True
