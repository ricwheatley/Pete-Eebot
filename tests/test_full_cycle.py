from __future__ import annotations

from datetime import date, timedelta

from pete_e.domain.cycle_service import CycleService


def test_cycle_service_detects_four_week_rollover():
    active_plan = {"start_date": date(2024, 1, 1), "weeks": 4}
    reference = date(2024, 1, 28)  # Sunday of week four

    assert CycleService.should_rollover(active_plan, reference) is True


def test_cycle_service_requires_active_plan():
    assert CycleService.should_rollover(None, date.today()) is False


def test_cycle_service_waits_until_end_of_block():
    active_plan = {"start_date": date(2024, 1, 1), "weeks": 6}
    reference = active_plan["start_date"] + timedelta(days=7)

    assert CycleService.should_rollover(active_plan, reference) is False
