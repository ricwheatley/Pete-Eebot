from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from pete_e.application.exceptions import PlanRolloverError
from pete_e.application.orchestrator import CycleRolloverResult, Orchestrator, WeeklyAutomationResult, WeeklyCalibrationResult


class StubPlanService:
    def __init__(self, plan_id: int = 123) -> None:
        self.plan_id = plan_id
        self.calls: list[date] = []

    def create_next_plan_for_cycle(self, *, start_date: date) -> int:
        self.calls.append(start_date)
        return self.plan_id


class StubExportService:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int, date]] = []

    def export_plan_week(self, *, plan_id: int, week_number: int, start_date: date, force_overwrite: bool = False):
        self.calls.append((plan_id, week_number, start_date))
        return {"status": "exported"}


class StubDal:
    def __init__(self, active_plan: dict | None = None) -> None:
        self._active_plan = active_plan or {"id": 7, "start_date": date(2024, 1, 1), "weeks": 4}

    def get_active_plan(self) -> dict | None:
        return self._active_plan

    def close(self) -> None:  # pragma: no cover - not used in tests
        pass


def make_orchestrator(plan_service: StubPlanService | None = None, export_service: StubExportService | None = None, dal: StubDal | None = None) -> Orchestrator:
    dal = dal or StubDal()
    return Orchestrator(
        dal=dal,
        wger_client=SimpleNamespace(),
        plan_service=plan_service or StubPlanService(),
        export_service=export_service or StubExportService(),
    )


def test_run_cycle_rollover_creates_plan_and_exports(monkeypatch: pytest.MonkeyPatch) -> None:
    plan_service = StubPlanService(plan_id=77)
    export_service = StubExportService()
    orch = make_orchestrator(plan_service=plan_service, export_service=export_service)

    result = orch.run_cycle_rollover(reference_date=date(2024, 5, 5))

    assert isinstance(result, CycleRolloverResult)
    assert result.created is True
    assert result.exported is True
    assert plan_service.calls == [date(2024, 5, 6)]
    assert export_service.calls == [(77, 1, date(2024, 5, 6))]


def test_run_cycle_rollover_raises_when_plan_creation_errors() -> None:
    class ExplodingPlanService(StubPlanService):
        def create_next_plan_for_cycle(self, *, start_date: date) -> int:
            raise RuntimeError("boom")

    orch = make_orchestrator(plan_service=ExplodingPlanService())

    with pytest.raises(PlanRolloverError) as excinfo:
        orch.run_cycle_rollover(reference_date=date(2024, 9, 1))

    assert "boom" in str(excinfo.value)


def test_run_end_to_end_week_triggers_rollover_when_due(monkeypatch: pytest.MonkeyPatch) -> None:
    plan_service = StubPlanService(plan_id=400)
    export_service = StubExportService()
    # Active plan starts four weeks before reference date so rollover is due
    active_plan = {"id": 5, "start_date": date(2024, 1, 1), "weeks": 4}
    dal = StubDal(active_plan=active_plan)
    orch = make_orchestrator(plan_service=plan_service, export_service=export_service, dal=dal)

    # Provide deterministic calibration result
    monkeypatch.setattr(
        Orchestrator,
        "run_weekly_calibration",
        lambda self, reference_date: WeeklyCalibrationResult(message="ok", validation=None),
    )

    outcome = orch.run_end_to_end_week(reference_date=date(2024, 1, 28))

    assert isinstance(outcome, WeeklyAutomationResult)
    assert outcome.rollover_triggered is True
    assert outcome.rollover.plan_id == 400
