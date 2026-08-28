"""Orchestrator contract for the injected weekly-plan application port."""

from __future__ import annotations

from datetime import date

from pete_e.application.orchestrator import Orchestrator
from pete_e.application.weekly_plan_context import (
    select_compatible_weekly_plan_message_builder,
)


class _WeeklyPlanBuilder:
    def __init__(self) -> None:
        self.calls: list[tuple[date | None, date | None]] = []

    def build_message(
        self,
        *,
        target_date: date | None = None,
        current_date: date | None = None,
    ) -> str:
        self.calls.append((target_date, current_date))
        return "application weekly plan"


def test_orchestrator_delegates_weekly_plan_message_to_injected_port() -> None:
    builder = _WeeklyPlanBuilder()
    orchestrator = object.__new__(Orchestrator)
    orchestrator.weekly_plan_message_builder = builder
    target = date(2024, 9, 9)
    current = date(2024, 9, 8)

    assert (
        orchestrator.build_weekly_plan_message(
            target_date=target,
            current_date=current,
        )
        == "application weekly plan"
    )
    assert builder.calls == [(target, current)]
    assert select_compatible_weekly_plan_message_builder(orchestrator) is builder
