"""Pure normalization and seven-day analysis for body-age history."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import SupportsFloat, cast

from pete_e.domain.body_age_history import BodyAgeHistoryRow


@dataclass(frozen=True)
class BodyAgeTrend:
    """Latest body-age reading with an exact-date seven-day delta."""

    sample_date: date | None
    value: float | None
    delta: float | None


@dataclass(frozen=True)
class _BodyAgePoint:
    sample_date: date
    value: float


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, float):
        return value
    if isinstance(value, (int, Decimal)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    try:
        return float(cast(SupportsFloat, value))
    except (TypeError, ValueError):
        return None


def _to_date(value: object) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return date.fromisoformat(stripped[:10])
        except ValueError:
            return None
    return None


def extract_body_age_value(row: BodyAgeHistoryRow) -> float | None:
    """Return the legacy flat or nested body-age value from one typed row."""
    value = row.get("body_age_years")
    if value is None:
        body_section = row.get("body")
        if isinstance(body_section, dict):
            value = body_section.get("body_age_years")
    return _to_float(value)


def _normalize_body_age_row(
    raw_row: object,
    *,
    start_date: date,
    target_date: date,
) -> _BodyAgePoint | None:
    if not isinstance(raw_row, dict):
        return None
    row = cast(BodyAgeHistoryRow, raw_row)
    row_date = _to_date(row.get("date"))
    if row_date is None:
        return None
    if row_date < start_date or row_date > target_date:
        return None
    value = extract_body_age_value(row)
    if value is None:
        return None
    return _BodyAgePoint(sample_date=row_date, value=value)


def analyze_body_age_trend(
    rows: Iterable[BodyAgeHistoryRow],
    target_date: date,
) -> BodyAgeTrend:
    """Normalize rows and select the latest and exact seven-day body-age points."""
    start_date = target_date - timedelta(days=7)
    points = [
        point
        for raw_row in rows
        if (
            point := _normalize_body_age_row(
                raw_row,
                start_date=start_date,
                target_date=target_date,
            )
        )
        is not None
    ]
    if not points:
        return BodyAgeTrend(sample_date=None, value=None, delta=None)

    points.sort(key=lambda point: point.sample_date)
    latest = points[-1]
    week_value = next(
        (
            point.value
            for point in points
            if point.sample_date == target_date - timedelta(days=7)
        ),
        None,
    )
    delta = round(latest.value - week_value, 1) if week_value is not None else None
    return BodyAgeTrend(
        sample_date=latest.sample_date,
        value=round(latest.value, 1),
        delta=delta,
    )


__all__ = [
    "BodyAgeTrend",
    "analyze_body_age_trend",
    "extract_body_age_value",
]
