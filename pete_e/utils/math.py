"""Numeric helpers shared across Pete-E modules."""

from __future__ import annotations

from typing import Iterable, Optional


def average(values: Iterable[Optional[float]]) -> Optional[float]:
    """Compute the mean of ``values`` while skipping ``None`` entries."""

    filtered = [value for value in values if value is not None]
    if not filtered:
        return None
    return sum(filtered) / len(filtered)


def mean_or_none(values: Iterable[float]) -> Optional[float]:
    """Return the arithmetic mean of ``values`` or ``None`` when empty."""

    values_list = list(values)
    if not values_list:
        return None
    return sum(values_list) / len(values_list)


def near(value: float | None, target: float | None, *, tolerance: float = 1e-6) -> bool:
    """Return ``True`` when ``value`` is within ``tolerance`` of ``target``."""

    if value is None or target is None:
        return False
    return abs(value - target) <= tolerance
