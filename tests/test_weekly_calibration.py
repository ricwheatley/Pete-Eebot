from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from pete_e.application.orchestrator import Orchestrator


class DummyDal:
    def get_active_plan(self):
        return {"start_date": date(2024, 1, 1), "weeks": 4}

    def close(self):  # pragma: no cover
        pass


class StubValidationService:
    def __init__(self):
        self.calls: list[date] = []

    def validate_and_adjust_plan(self, week_start: date):
        self.calls.append(week_start)
        return SimpleNamespace(explanation="ok", needs_backoff=False)


def build_orchestrator(validation_service: StubValidationService | None = None):
    validation_service = validation_service or StubValidationService()
    return Orchestrator(
        dal=DummyDal(),
        wger_client=SimpleNamespace(),
        plan_service=SimpleNamespace(create_next_plan_for_cycle=lambda start_date: 0),
        export_service=SimpleNamespace(export_plan_week=lambda plan_id, week_number, start_date, force_overwrite=True: None),
        validation_service=validation_service,
    )


def test_run_weekly_calibration_uses_next_monday(monkeypatch):
    validation_service = StubValidationService()
    orch = build_orchestrator(validation_service)
    orch.run_weekly_calibration(reference_date=date(2024, 3, 6))  # Wednesday

    assert validation_service.calls == [date(2024, 3, 11)]
