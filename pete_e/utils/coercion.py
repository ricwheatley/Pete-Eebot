"""Shared coercion helpers for date/time and numeric values."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any


def coerce_decimal_to_float(value: Any) -> Any:
    """Convert ``Decimal`` to ``float`` while preserving other values."""

    if isinstance(value, Decimal):
        return float(value)
    return value


def coerce_numeric(value: Any) -> float | int | None:
    """Coerce common numeric values while preserving ``bool`` and ``None``."""

    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def coerce_date(value: Any) -> date | None:
    """Best-effort conversion to ``date`` from supported date-like values."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def coerce_int(value: Any) -> int | None:
    """Best-effort conversion to ``int`` compatible with existing strength-test rules."""

    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def coerce_float(value: Any) -> float | None:
    """Best-effort conversion to ``float``."""

    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
