from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

from pete_e.application.orchestrator import (
    Orchestrator,
    WeeklyCalibrationResult,
    CycleRolloverResult,
)
from pete_e.domain.cycle_service import CycleService
from tests.di_utils import build_stub_container


def test_check_and_rollover_requires_four_weeks_and_sunday():
    service = CycleService()
    plan = {"start_date": date(2024, 1, 1)}  # Monday

    fourth_sunday = date(2024, 1, 28)
    assert service.check_and_rollover(plan, fourth_sunday) is True

    third_sunday = fourth_sunday - timedelta(weeks=1)
    assert service.check_and_rollover(plan, third_sunday) is False

    midweek = fourth_sunday.replace(day=26)  # Friday of week four
    assert service.check_and_rollover(plan, midweek) is False


def test_orchestrator_delegates_rollover_decision():
    dal = MagicMock()
    active_plan = {"start_date": date(2024, 1, 1)}
    dal.get_active_plan.return_value = active_plan

    cycle_service = MagicMock()
    cycle_service.check_and_rollover.return_value = True

    container = build_stub_container(
        dal=dal,
        wger_client=MagicMock(),
        plan_service=MagicMock(),
        export_service=MagicMock(),
    )
    orchestrator = Orchestrator(container=container, cycle_service=cycle_service)

    orchestrator.run_weekly_calibration = MagicMock(
        return_value=WeeklyCalibrationResult(message="ok")
    )
    orchestrator.run_cycle_rollover = MagicMock(
        return_value=CycleRolloverResult(plan_id=1, created=True, exported=True)
    )

    today = date(2024, 1, 28)
    result = orchestrator.run_end_to_end_week(today)

    cycle_service.check_and_rollover.assert_called_once_with(active_plan, today)
    orchestrator.run_cycle_rollover.assert_called_once_with(today)
    assert result.rollover_triggered is True
