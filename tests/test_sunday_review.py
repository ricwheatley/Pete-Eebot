from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from pete_e.application.orchestrator import Orchestrator


class PassiveDal:
    def __init__(self) -> None:
        self._active_plan = {"start_date": date(2024, 1, 1), "weeks": 8}

    def get_active_plan(self):
        return self._active_plan

    def close(self) -> None:  # pragma: no cover
        pass


def build_orchestrator():
    return Orchestrator(
        dal=PassiveDal(),
        wger_client=SimpleNamespace(),
        plan_service=SimpleNamespace(create_next_plan_for_cycle=lambda start_date: 0),
        export_service=SimpleNamespace(export_plan_week=lambda plan_id, week_number, start_date, force_overwrite=True: None),
    )


def test_run_end_to_end_week_skips_rollover_when_not_due(monkeypatch):
    orch = build_orchestrator()
    monkeypatch.setattr(
        Orchestrator,
        "run_weekly_calibration",
        lambda self, reference_date: SimpleNamespace(message="ok", validation=None),
        raising=False,
    )

    result = orch.run_end_to_end_week(reference_date=date(2024, 1, 7))

    assert result.rollover_triggered is False
    assert result.rollover is None
