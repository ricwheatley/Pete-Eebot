from __future__ import annotations

from datetime import date

from pete_e.domain.daily_sync import (
    AppleHealthImportSummary,
    AppleHealthIngestResult,
    DailySyncService,
)
from pete_e.domain.wger_workouts import (
    WgerWorkoutImportSummary,
    WgerWorkoutIngestResult,
)


class _Repository:
    def __init__(self) -> None:
        self.refresh_days: list[int] = []
        self.actual_refreshes = 0

    def save_withings_daily(self, **_kwargs):
        return None

    def save_withings_measure_groups(self, **_kwargs):
        return None

    def refresh_daily_summary(self, *, days: int):
        self.refresh_days.append(days)

    def refresh_actual_view(self):
        self.actual_refreshes += 1


class _Withings:
    def get_summary(self, *, days_back: int):  # noqa: ARG002
        return None


class _Apple:
    def ingest(self):
        return AppleHealthIngestResult(
            success=True,
            summary=AppleHealthImportSummary((), 0, 0, 0, 0),
            statuses={"Apple Health": "ok"},
        )


class _Wger:
    def __init__(self, *, success: bool = True) -> None:
        self.success = success
        self.calls: list[tuple[date, date, bool]] = []

    def ingest(self, *, start_date: date, end_date: date, dry_run: bool = False):
        self.calls.append((start_date, end_date, dry_run))
        if not self.success:
            return WgerWorkoutIngestResult(
                success=False,
                failures=("Wger",),
                statuses={"Wger": "failed"},
            )
        return WgerWorkoutIngestResult(
            success=True,
            summary=WgerWorkoutImportSummary(start_date, end_date, 0, 0, 0, 0),
            statuses={"Wger": "ok"},
        )


def test_full_sync_reconciles_eight_calendar_dates_before_refreshing_views() -> None:
    repository = _Repository()
    wger = _Wger()
    service = DailySyncService(
        repository=repository,
        withings_source=_Withings(),
        apple_ingestor=_Apple(),
        wger_ingestor=wger,
        clock=lambda: date(2026, 8, 23),
    )

    result = service.run_full(days=3)

    assert result.success is True
    assert wger.calls == [(date(2026, 8, 16), date(2026, 8, 23), False)]
    assert repository.refresh_days == [7]
    assert repository.actual_refreshes == 1
    assert result.statuses == {
        "Withings": "ok",
        "Apple Health": "ok",
        "Wger": "ok",
        "Database": "ok",
    }


def test_full_sync_does_not_refresh_derived_views_after_wger_failure() -> None:
    repository = _Repository()
    service = DailySyncService(
        repository=repository,
        withings_source=_Withings(),
        apple_ingestor=_Apple(),
        wger_ingestor=_Wger(success=False),
        clock=lambda: date(2026, 8, 23),
    )

    result = service.run_full(days=3)

    assert result.success is False
    assert result.failures == ("Wger",)
    assert result.statuses["Database"] == "skipped"
    assert repository.refresh_days == []
    assert repository.actual_refreshes == 0


def test_wger_only_sync_uses_explicit_window_before_refreshing_views() -> None:
    repository = _Repository()
    wger = _Wger()
    service = DailySyncService(
        repository=repository,
        withings_source=_Withings(),
        apple_ingestor=_Apple(),
        wger_ingestor=wger,
        clock=lambda: date(2026, 8, 23),
    )

    result = service.run_wger_only(
        start_date=date(2026, 8, 17),
        end_date=date(2026, 8, 23),
    )

    assert result.success is True
    assert wger.calls == [(date(2026, 8, 17), date(2026, 8, 23), False)]
    assert repository.refresh_days == [8]
    assert repository.actual_refreshes == 1
    assert result.statuses == {"Wger": "ok", "Database": "ok"}
