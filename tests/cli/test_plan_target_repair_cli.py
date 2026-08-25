from __future__ import annotations

from datetime import date

from typer.testing import CliRunner

from pete_e.cli import messenger


def test_plan_target_repair_requires_explicit_confirmation(monkeypatch) -> None:
    monkeypatch.setattr(
        messenger,
        "_build_orchestrator",
        lambda: (_ for _ in ()).throw(AssertionError("must not build orchestrator")),
    )

    result = CliRunner().invoke(messenger.app, ["repair-plan-targets"])

    assert result.exit_code == 2
    assert "explicit --yes confirmation" in result.output


def test_plan_target_repair_runs_guarded_recovery(monkeypatch) -> None:
    calls: list[object] = []

    class Orchestrator:
        def repair_active_plan_targets(self, reference_date: date):
            calls.append(reference_date)
            return {
                "plan_id": 17,
                "workouts_updated": 6,
                "replacement": {"routine_id": 43},
            }

        def close(self):
            calls.append("closed")

    monkeypatch.setattr(messenger, "_build_orchestrator", Orchestrator)
    monkeypatch.setattr(
        messenger,
        "_run_cli_application_job",
        lambda **kwargs: kwargs["callback"](),
    )

    result = CliRunner().invoke(
        messenger.app,
        [
            "repair-plan-targets",
            "--reference-date",
            "2026-08-25",
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert calls == [date(2026, 8, 25), "closed"]
    assert "6 workout target(s) repaired" in result.output
    assert "Wger routine 43 published" in result.output
