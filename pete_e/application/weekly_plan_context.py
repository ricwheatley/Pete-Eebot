"""Composition adapter for the established structured weekly coach state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import cast

from pete_e.application import api_services
from pete_e.application.composition import provide_weekly_plan_message_builder
from pete_e.application.weekly_plan_message import (
    WeeklyPlanCoachStateProvider,
    WeeklyPlanMessageBuilder,
)
from pete_e.domain import auth


@dataclass(frozen=True)
class MetricsWeeklyPlanCoachStateProvider:
    """Load the existing MetricsService state under the trusted CLI principal."""

    reader_source: object

    def __call__(self, target: date) -> object:
        metrics_service = api_services.MetricsService(self.reader_source)
        return metrics_service.coach_state(
            target.isoformat(),
            principal=auth.trusted_profile_reader("local-cli", auth_scheme="cli"),
        )


def provide_weekly_plan_coach_state(
    reader_source: object | None,
) -> WeeklyPlanCoachStateProvider | None:
    """Return no provider when the legacy orchestration object has no DAL."""

    if reader_source is None:
        return None
    return MetricsWeeklyPlanCoachStateProvider(reader_source)


def select_compatible_weekly_plan_message_builder(
    orchestrator: object,
) -> WeeklyPlanMessageBuilder:
    """Expose an injected port or adapt the legacy duck-typed orchestrator."""

    configured = getattr(orchestrator, "weekly_plan_message_builder", None)
    if configured is not None:
        return cast(WeeklyPlanMessageBuilder, configured)
    reader_source = getattr(orchestrator, "dal", None)
    return provide_weekly_plan_message_builder(
        reader_source=reader_source,
        renderer=getattr(orchestrator, "narrative_builder", None),
        voice_source=getattr(orchestrator, "voice_service", None),
        coach_state_provider=provide_weekly_plan_coach_state(reader_source),
    )


__all__ = [
    "MetricsWeeklyPlanCoachStateProvider",
    "provide_weekly_plan_coach_state",
    "select_compatible_weekly_plan_message_builder",
]
