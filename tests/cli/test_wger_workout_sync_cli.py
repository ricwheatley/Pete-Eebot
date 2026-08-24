from __future__ import annotations

from datetime import date

from typer.testing import CliRunner

from pete_e.cli import messenger
from pete_e.domain.wger_workouts import (
    WgerWorkoutImportSummary,
    WgerWorkoutIngestResult,
)


def test_wger_sync_cli_uses_explicit_bounded_window(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(*, start_date, end_date, dry_run):
        captured.update(
            start_date=start_date,
            end_date=end_date,
            dry_run=dry_run,
        )
        return WgerWorkoutIngestResult(
            success=True,
            summary=WgerWorkoutImportSummary(
                start_date,
                end_date,
                fetched=4,
                accepted=4,
                skipped=0,
                stored=0,
                dry_run=dry_run,
            ),
            statuses={"Wger": "dry-run"},
        )

    monkeypatch.setattr(messenger, "run_wger_workout_sync", fake_run)
    monkeypatch.setattr(
        messenger,
        "_run_cli_application_job",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("dry run should not create a durable job")
        ),
    )

    result = CliRunner().invoke(
        messenger.app,
        [
            "wger-sync",
            "--from-date",
            "2026-08-17",
            "--to-date",
            "2026-08-23",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert captured == {
        "start_date": date(2026, 8, 17),
        "end_date": date(2026, 8, 23),
        "dry_run": True,
    }
    assert "2026-08-17 to 2026-08-23" in result.output


def test_wger_sync_cli_rejects_reversed_dates() -> None:
    result = CliRunner().invoke(
        messenger.app,
        [
            "wger-sync",
            "--from-date",
            "2026-08-23",
            "--to-date",
            "2026-08-17",
        ],
    )

    assert result.exit_code == 2
    assert "--from-date must be on or before --to-date" in result.output
