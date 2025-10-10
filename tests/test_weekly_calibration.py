from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from pete_e.application.orchestrator import Orchestrator


class DummyDal:
    def get_active_plan(self):
        return {"start_date": date(2024, 1, 1), "weeks": 4}

    def close(self):  # pragma: no cover
        pass


def build_orchestrator():
    return Orchestrator(
        dal=DummyDal(),
        wger_client=SimpleNamespace(),
        plan_service=SimpleNamespace(create_next_plan_for_cycle=lambda start_date: 0),
        export_service=SimpleNamespace(export_plan_week=lambda plan_id, week_number, start_date, force_overwrite=True: None),
    )


def test_run_weekly_calibration_uses_next_monday(monkeypatch):
    captured = {}

    def fake_validate(dal, week_start):
        captured["week_start"] = week_start
        return SimpleNamespace(explanation="ok", needs_backoff=False)

    monkeypatch.setattr("pete_e.application.orchestrator.validate_and_adjust_plan", fake_validate)

    orch = build_orchestrator()
    orch.run_weekly_calibration(reference_date=date(2024, 3, 6))  # Wednesday

    assert captured["week_start"] == date(2024, 3, 11)
