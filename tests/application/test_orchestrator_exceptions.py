from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from pete_e.application.exceptions import DataAccessError, PlanRolloverError, ValidationError
from pete_e.application.orchestrator import Orchestrator
from tests.di_utils import build_stub_container


class StubDal:
    def __init__(self, *, active_plan: dict | None = None, should_fail: bool = False) -> None:
        self._active_plan = active_plan
        self._should_fail = should_fail

    def get_active_plan(self):
        if self._should_fail:
            raise RuntimeError("database down")
        return self._active_plan or {"start_date": date(2024, 1, 1), "weeks": 4}

    def close(self) -> None:  # pragma: no cover - not used here
        pass


class ExplodingValidationService:
    def validate_and_adjust_plan(self, week_start: date):
        raise ValueError("validation boom")


class ExplodingCycleService:
    def check_and_rollover(self, active_plan, today: date):
        raise RuntimeError("cycle boom")


def _make_orchestrator(**overrides) -> Orchestrator:
    container = build_stub_container(
        dal=overrides.get("dal", StubDal()),
        wger_client=SimpleNamespace(),
        plan_service=overrides.get(
            "plan_service",
            SimpleNamespace(create_next_plan_for_cycle=lambda start_date: 99),
        ),
        export_service=overrides.get(
            "export_service",
            SimpleNamespace(
                export_plan_week=lambda plan_id, week_number, start_date, force_overwrite=True: {
                    "status": "exported"
                }
            ),
        ),
    )
    return Orchestrator(
        container=container,
        validation_service=overrides.get("validation_service"),
        cycle_service=overrides.get("cycle_service"),
    )


def test_run_weekly_calibration_raises_validation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []
    monkeypatch.setattr(
        "pete_e.application.orchestrator.log_utils.error",
        lambda message, tag=None: captured.append(message),
    )

    orch = _make_orchestrator(validation_service=ExplodingValidationService())

    with pytest.raises(ValidationError) as excinfo:
        orch.run_weekly_calibration(reference_date=date(2024, 5, 1))

    assert "validation boom" in str(excinfo.value)
    assert captured and "validation boom" in captured[0]


def test_run_cycle_rollover_wraps_export_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []
    monkeypatch.setattr(
        "pete_e.application.orchestrator.log_utils.error",
        lambda message, tag=None: captured.append(message),
    )

    def _explode(**kwargs):
        raise RuntimeError("export boom")

    orch = _make_orchestrator(
        export_service=SimpleNamespace(export_plan_week=_explode)
    )

    with pytest.raises(PlanRolloverError) as excinfo:
        orch.run_cycle_rollover(reference_date=date(2024, 5, 5))

    assert "export boom" in str(excinfo.value)
    assert captured and "export boom" in captured[0]


def test_run_end_to_end_week_raises_for_dal_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []
    monkeypatch.setattr(
        "pete_e.application.orchestrator.log_utils.error",
        lambda message, tag=None: captured.append(message),
    )

    orch = _make_orchestrator(
        dal=StubDal(should_fail=True),
        validation_service=SimpleNamespace(
            validate_and_adjust_plan=lambda week_start: SimpleNamespace(
                explanation="ok",
                needs_backoff=False,
            )
        ),
    )

    with pytest.raises(DataAccessError) as excinfo:
        orch.run_end_to_end_week(reference_date=date(2024, 5, 5))

    assert "database down" in str(excinfo.value)
    assert captured and "database down" in captured[0]


def test_run_end_to_end_week_raises_for_cycle_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []
    monkeypatch.setattr(
        "pete_e.application.orchestrator.log_utils.error",
        lambda message, tag=None: captured.append(message),
    )

    orch = _make_orchestrator(
        cycle_service=ExplodingCycleService(),
        validation_service=SimpleNamespace(
            validate_and_adjust_plan=lambda week_start: SimpleNamespace(
                explanation="ok",
                needs_backoff=False,
            )
        ),
    )

    with pytest.raises(PlanRolloverError) as excinfo:
        orch.run_end_to_end_week(reference_date=date(2024, 5, 5))

    assert "cycle boom" in str(excinfo.value)
    assert captured and "cycle boom" in captured[0]
