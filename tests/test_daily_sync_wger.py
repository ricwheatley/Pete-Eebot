from __future__ import annotations

from datetime import date
from typing import Any

from pete_e.domain.daily_sync import (
    AppleHealthImportSummary,
    AppleHealthIngestResult,
    DailySyncService,
)


class _Repository:
    def refresh_daily_summary(self, *, days: int) -> None:
        pass

    def refresh_actual_view(self) -> None:
        pass


class _Withings:
    def get_summary(self, *, days_back: int) -> None:
        return None


class _Apple:
    def ingest(self) -> AppleHealthIngestResult:
        return AppleHealthIngestResult(
            success=True,
            summary=AppleHealthImportSummary(
                sources=(), workouts=0, daily_points=0, hr_days=0, sleep_days=0
            ),
            statuses={"Apple Health": "ok"},
        )


class _Wger:
    def __init__(self) -> None:
        self.calls: list[tuple[date, date]] = []

    def sync(self, *, start_date: date, end_date: date) -> int:
        self.calls.append((start_date, end_date))
        return 4


def test_full_daily_sync_persists_wger_logs(monkeypatch: Any) -> None:
    monkeypatch.setattr("pete_e.domain.daily_sync.date", _DateStub)
    wger = _Wger()
    service = DailySyncService(
        repository=_Repository(),
        withings_source=_Withings(),
        apple_ingestor=_Apple(),
        wger_ingestor=wger,
    )

    result = service.run_full(days=7)

    assert result.success is True
    assert result.statuses["Wger"] == "ok"
    assert wger.calls == [(date(2024, 8, 5), date(2024, 8, 11))]


class _DateStub(date):
    @classmethod
    def today(cls) -> date:
        return cls(2024, 8, 11)


def test_full_daily_sync_reports_wger_failure(monkeypatch: Any) -> None:
    monkeypatch.setattr("pete_e.domain.daily_sync.date", _DateStub)

    class BrokenWger:
        def sync(self, *, start_date: date, end_date: date) -> int:
            raise RuntimeError("upstream unavailable")

    service = DailySyncService(
        repository=_Repository(),
        withings_source=_Withings(),
        apple_ingestor=_Apple(),
        wger_ingestor=BrokenWger(),
    )

    result = service.run_full(days=1)

    assert result.success is False
    assert result.failures == ("Wger",)
    assert result.statuses["Wger"] == "failed"
