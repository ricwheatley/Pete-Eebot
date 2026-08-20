"""Authoritative duration contract for standard training-plan generation."""

from __future__ import annotations

from enum import IntEnum

from pete_e.application.exceptions import ValidationError


class PlanDurationWeeks(IntEnum):
    """Plan lengths that the standard 5/3/1 generator implements end to end."""

    FOUR_WEEK_BLOCK = 4


SUPPORTED_PLAN_WEEKS = tuple(duration.value for duration in PlanDurationWeeks)
DEFAULT_PLAN_WEEKS = PlanDurationWeeks.FOUR_WEEK_BLOCK.value
PLAN_DURATION_HELP = "Standard plan generation supports one fixed 4-week 5/3/1 block."


def validate_plan_weeks(weeks: int) -> int:
    """Return a supported standard-plan duration or raise a client-safe error."""

    if not isinstance(weeks, int) or isinstance(weeks, bool) or weeks not in SUPPORTED_PLAN_WEEKS:
        raise ValidationError(
            f"Unsupported plan duration: {weeks!r}. Only 4-week plan generation is currently supported.",
            code="unsupported_plan_duration",
        )
    return int(weeks)


__all__ = [
    "DEFAULT_PLAN_WEEKS",
    "PLAN_DURATION_HELP",
    "PlanDurationWeeks",
    "SUPPORTED_PLAN_WEEKS",
    "validate_plan_weeks",
]
