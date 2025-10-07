"""Type conversion helpers used across the Pete-E codebase."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional


def to_float(value: Any) -> Optional[float]:
    """Safely convert ``value`` to ``float`` where possible."""

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
        return float(value)
    except (TypeError, ValueError):
        return None


def to_date(value: Any) -> Optional[date]:
    """Best-effort conversion of common date representations to ``date``."""

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


def minutes_to_hours(value: Any) -> Optional[float]:
    """Convert a minutes value into hours when possible."""

    numeric = to_float(value)
    if numeric is None:
        return None
    return numeric / 60.0
