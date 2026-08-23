"""Typed weekly metric analysis, independent from narrative presentation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Protocol, Sequence, TypeAlias, cast


DayPayload: TypeAlias = dict[str, Any]
TrendSample: TypeAlias = tuple[date, DayPayload]


class ComparisonFormatter(Protocol):
    """Format a current value relative to an optional previous value."""

    def __call__(
        self,
        current: int | float,
        previous: int | float | None,
        unit: str = "",
        context: str = "",
    ) -> str: ...


class TrendFormatter(Protocol):
    """Render trend lines for dated metric samples."""

    def __call__(
        self,
        samples: Sequence[tuple[date | datetime, Mapping[str, Any]]],
        *,
        as_of: date | None = None,
        limit: int | None = None,
    ) -> list[str]: ...


class DateParser(Protocol):
    """Convert an incoming day key to a calendar date when possible."""

    def __call__(self, value: Any) -> date | None: ...


@dataclass(frozen=True, slots=True)
class WeeklyNarrativeAnalysis:
    """Ordered metric insights ready for the narrative presentation layer."""

    insights: tuple[str, ...]


def _dated_samples(
    days: Mapping[str, Any], parse_date: DateParser
) -> list[TrendSample]:
    samples: list[TrendSample] = []
    for iso_day in sorted(days.keys()):
        parsed_day = parse_date(iso_day)
        if parsed_day is None:
            continue
        payload = days.get(iso_day)
        if isinstance(payload, dict):
            samples.append((parsed_day, payload))
    samples.sort(key=lambda item: item[0])
    return samples


def _window(
    days: Mapping[str, Any], today: date, start: int, end: int
) -> list[DayPayload]:
    keys = [
        (today - timedelta(days=offset)).isoformat() for offset in range(start, end + 1)
    ]
    return [cast(DayPayload, days[key]) for key in keys if key in days]


def _strength_insight(
    current: list[DayPayload],
    previous: list[DayPayload],
    compare: ComparisonFormatter,
) -> str | None:
    total_volume = sum(
        exercise["volume_kg"] for day in current for exercise in day.get("strength", [])
    )
    previous_volume = (
        sum(
            exercise["volume_kg"]
            for day in previous
            for exercise in day.get("strength", [])
        )
        if previous
        else None
    )
    if not total_volume:
        return None
    comparison = compare(
        int(total_volume),
        int(previous_volume) if previous_volume else None,
        "kg",
    )
    return f"Lifting volume hit {comparison} this week."


def _steps_insight(
    current: list[DayPayload],
    previous: list[DayPayload],
    compare: ComparisonFormatter,
) -> str | None:
    total_steps = sum(day.get("activity", {}).get("steps", 0) for day in current)
    previous_steps = (
        sum(day.get("activity", {}).get("steps", 0) for day in previous)
        if previous
        else None
    )
    if not total_steps:
        return None
    comparison = compare(int(total_steps), previous_steps, "steps", "this week")
    return f"You clocked {comparison}."


def _sleep_insight(
    current: list[DayPayload],
    previous: list[DayPayload],
    compare: ComparisonFormatter,
) -> str | None:
    sleep_minutes = [day.get("sleep", {}).get("asleep_minutes", 0) for day in current]
    previous_sleep = (
        [day.get("sleep", {}).get("asleep_minutes", 0) for day in previous]
        if previous
        else []
    )
    if not sleep_minutes:
        return None
    average_sleep = round(sum(sleep_minutes) / len(sleep_minutes) / 60)
    previous_average = (
        round(sum(previous_sleep) / len(previous_sleep) / 60)
        if previous_sleep
        else None
    )
    comparison = compare(average_sleep, previous_average, "h", "per night")
    return f"Average sleep was {comparison}."


def _body_metric(day: DayPayload, field: str) -> float | None:
    body_section = day.get("body")
    value = body_section.get(field) if isinstance(body_section, dict) else None
    if value is None:
        value = day.get(field)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _body_metric_values(days: list[DayPayload], field: str) -> list[float]:
    values: list[float] = []
    for day in days:
        value = _body_metric(day, field)
        if value is not None:
            values.append(value)
    return values


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _muscle_insight(
    current: list[DayPayload], previous: list[DayPayload]
) -> str | None:
    current_average = _average(_body_metric_values(current, "muscle_pct"))
    if current_average is None:
        return None
    previous_average = _average(_body_metric_values(previous, "muscle_pct"))
    if previous_average is None:
        return f"Muscle composition averaged {current_average:.1f}% this week."
    difference = round(current_average - previous_average, 1)
    if abs(difference) < 0.5:
        return None
    direction = "up" if difference > 0 else "down"
    return (
        f"Muscle composition averaged {current_average:.1f}% this week, "
        f"{direction} {abs(difference):.1f}% from last week."
    )


def _body_age_insight(
    current: list[DayPayload], previous: list[DayPayload]
) -> str | None:
    current_average = _average(_body_metric_values(current, "body_age_years"))
    if current_average is None:
        return None
    previous_average = _average(_body_metric_values(previous, "body_age_years"))
    if previous_average is None:
        return f"Body Age averaged {current_average:.1f}y this week."
    difference = round(current_average - previous_average, 1)
    if difference > 0:
        comparison = f"up {abs(difference):.1f}y from last week"
    elif difference < 0:
        comparison = f"down {abs(difference):.1f}y from last week"
    else:
        comparison = "matching last week"
    return f"Body Age averaged {current_average:.1f}y this week, {comparison}."


def _trend_insights(
    samples: list[TrendSample],
    today: date,
    trends: TrendFormatter,
) -> list[str]:
    if not samples:
        return []
    trend_as_of = min(today - timedelta(days=1), samples[-1][0])
    lines = trends(samples, as_of=trend_as_of, limit=2)
    if not lines:
        return []
    first_line, *extra_lines = lines
    return [f"Momentum backdrop - {first_line}", *extra_lines]


def analyze_weekly_metrics(
    days: Mapping[str, Any],
    *,
    today: date,
    compare: ComparisonFormatter,
    trends: TrendFormatter,
    parse_date: DateParser,
) -> WeeklyNarrativeAnalysis:
    """Analyze two UTC-relative weeks and return presentation-ready insights."""

    current = _window(days, today, 1, 7)
    previous = _window(days, today, 8, 14)
    insights = [
        insight
        for insight in (
            _strength_insight(current, previous, compare),
            _steps_insight(current, previous, compare),
            _sleep_insight(current, previous, compare),
            _muscle_insight(current, previous),
            _body_age_insight(current, previous),
        )
        if insight is not None
    ]
    insights.extend(_trend_insights(_dated_samples(days, parse_date), today, trends))
    return WeeklyNarrativeAnalysis(insights=tuple(insights))
