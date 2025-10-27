from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

import tests.config_stub  # noqa: F401

from pete_e.application.orchestrator import Orchestrator
from tests.di_utils import build_stub_container


class StubDal:
    def __init__(self, active_plan: dict | None = None):
        self._active_plan = active_plan or {"start_date": date(2024, 1, 1), "weeks": 4}

    def get_active_plan(self):
        return self._active_plan

    def close(self) -> None:  # pragma: no cover - unused
        pass


class StubValidationService:
    def __init__(self, decision):
        self.decision = decision
        self.calls: list[date] = []

    def validate_and_adjust_plan(self, week_start: date):
        self.calls.append(week_start)
        return self.decision


def _make_orchestrator(
    dal: StubDal | None = None,
    *,
    validation_service: StubValidationService | None = None,
):
    container = build_stub_container(
        dal=dal or StubDal(),
        wger_client=SimpleNamespace(),
        plan_service=SimpleNamespace(create_next_plan_for_cycle=lambda start_date: 5),
        export_service=SimpleNamespace(
            export_plan_week=lambda plan_id, week_number, start_date, force_overwrite=True, validation_decision=None: {"status": "exported"}
        ),
    )
    return Orchestrator(container=container, validation_service=validation_service)


def test_run_weekly_calibration_reports_message():
    result_obj = SimpleNamespace(explanation="All clear", needs_backoff=False)
    validation_service = StubValidationService(result_obj)

    orch = _make_orchestrator(validation_service=validation_service)
    result = orch.run_weekly_calibration(reference_date=date(2024, 5, 3))

    assert result.message == "All clear"
    assert result.validation is result_obj
    assert validation_service.calls == [date(2024, 5, 6)]


def test_run_end_to_end_week_triggers_rollover(monkeypatch: pytest.MonkeyPatch):
    plan_service_calls = []
    export_calls = []

    plan_service = SimpleNamespace(
        create_next_plan_for_cycle=lambda start_date: plan_service_calls.append(start_date) or 11
    )
    export_service = SimpleNamespace(
        export_plan_week=lambda plan_id, week_number, start_date, force_overwrite=True, validation_decision=None: export_calls.append(
            (plan_id, week_number, start_date, validation_decision)
        )
    )
    dal = StubDal(active_plan={"start_date": date(2024, 4, 1), "weeks": 4})
    container = build_stub_container(
        dal=dal,
        wger_client=SimpleNamespace(),
        plan_service=plan_service,
        export_service=export_service,
    )
    orch = Orchestrator(container=container)

    monkeypatch.setattr(
        Orchestrator,
        "run_weekly_calibration",
        lambda self, reference_date: SimpleNamespace(message="ok", validation=None),
        raising=False,
    )

    result = orch.run_end_to_end_week(reference_date=date(2024, 4, 28))

    assert result.rollover_triggered is True
    assert plan_service_calls == [date(2024, 4, 29)]
    assert export_calls == [(11, 1, date(2024, 4, 29), None)]


def test_run_end_to_end_week_exports_when_rollover_skipped(monkeypatch: pytest.MonkeyPatch):
    export_calls: list[tuple[int, int, date, object]] = []
    export_service = SimpleNamespace(
        export_plan_week=lambda plan_id, week_number, start_date, force_overwrite=True, validation_decision=None: export_calls.append(
            (plan_id, week_number, start_date, validation_decision)
        )
    )
    dal = StubDal(active_plan={"id": 13, "start_date": date(2024, 4, 22), "weeks": 4})
    container = build_stub_container(
        dal=dal,
        wger_client=SimpleNamespace(),
        plan_service=SimpleNamespace(create_next_plan_for_cycle=lambda start_date: 99),
        export_service=export_service,
    )
    orch = Orchestrator(container=container)

    monkeypatch.setattr(
        Orchestrator,
        "run_weekly_calibration",
        lambda self, reference_date: SimpleNamespace(message="ok", validation=None),
        raising=False,
    )

    result = orch.run_end_to_end_week(reference_date=date(2024, 4, 28))

    assert result.rollover_triggered is False
    assert export_calls == [(13, 2, date(2024, 4, 29), None)]
