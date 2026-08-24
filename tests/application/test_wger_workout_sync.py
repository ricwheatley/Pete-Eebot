from __future__ import annotations

from datetime import date

from pete_e.application.wger_workout_sync import run_wger_workout_sync
from pete_e.domain.wger_workouts import (
    WgerWorkoutImportSummary,
    WgerWorkoutIngestResult,
)


class _Ingestor:
    def ingest(self, *, start_date, end_date, dry_run=False):
        return WgerWorkoutIngestResult(
            success=True,
            summary=WgerWorkoutImportSummary(
                start_date,
                end_date,
                fetched=3,
                accepted=3,
                skipped=0,
                stored=0 if dry_run else 3,
                dry_run=dry_run,
            ),
            statuses={"Wger": "dry-run" if dry_run else "ok"},
        )


class _Repository:
    def __init__(self) -> None:
        self.summary_refreshes: list[tuple[date, date]] = []
        self.actual_refreshes = 0
        self.closed = False

    def refresh_daily_summary_range(self, start_date, end_date):
        self.summary_refreshes.append((start_date, end_date))

    def refresh_actual_view(self):
        self.actual_refreshes += 1

    def close(self):
        self.closed = True


def test_explicit_wger_sync_refreshes_only_requested_summary_range() -> None:
    repository = _Repository()

    result = run_wger_workout_sync(
        start_date=date(2026, 8, 17),
        end_date=date(2026, 8, 23),
        ingestor=_Ingestor(),
        repository=repository,
    )

    assert result.success is True
    assert result.statuses == {"Wger": "ok", "Database": "ok"}
    assert repository.summary_refreshes == [(date(2026, 8, 17), date(2026, 8, 23))]
    assert repository.actual_refreshes == 1
    assert repository.closed is False


def test_wger_dry_run_does_not_refresh_downstream_views() -> None:
    repository = _Repository()

    result = run_wger_workout_sync(
        start_date=date(2026, 8, 17),
        end_date=date(2026, 8, 23),
        dry_run=True,
        ingestor=_Ingestor(),
        repository=repository,
    )

    assert result.success is True
    assert result.statuses == {"Wger": "dry-run"}
    assert repository.summary_refreshes == []
    assert repository.actual_refreshes == 0
