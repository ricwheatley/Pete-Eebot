"""Utility helpers for loading aggregated metrics for narratives."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable, Dict, Iterable, Mapping, Optional

from pete_e.domain.data_access import DataAccessLayer
from pete_e.infrastructure import log_utils
from pete_e.utils import converters


def _window_values(
    series: Dict[date, Optional[float]],
    *,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> Iterable[float]:
    for point_date, value in series.items():
        if value is None:
            continue
        if start is not None and point_date < start:
            continue
        if end is not None and point_date >= end:
            continue
        yield value


def _average_window(
    series: Dict[date, Optional[float]],
    *,
    start: date,
    end: date,
) -> Optional[float]:
    values = list(_window_values(series, start=start, end=end))
    if not values:
        return None
    return sum(values) / len(values)


def _extreme_window(
    series: Dict[date, Optional[float]],
    *,
    start: Optional[date] = None,
    end: Optional[date] = None,
    reducer=max,
) -> Optional[float]:
    values = list(_window_values(series, start=start, end=end))
    if not values:
        return None
    return reducer(values)


def _build_metric_series(
    rows: Iterable[Mapping[str, Any]],
    column: str,
    transform: Optional[Callable[[Any], Optional[float]]],
) -> Dict[date, Optional[float]]:
    series: Dict[date, Optional[float]] = {}
    for row in rows:
        row_date = converters.to_date(row.get("date"))
        if row_date is None:
            continue
        raw_value = row.get(column)
        value = (
            transform(raw_value)
            if transform is not None
            else converters.to_float(raw_value)
        )
        series[row_date] = value
    return series


def _calculate_moving_averages(
    series: Dict[date, Optional[float]], *, reference: date
) -> Dict[str, Optional[float]]:
    yesterday = reference - timedelta(days=1)
    day_before = reference - timedelta(days=2)

    yesterday_value = series.get(yesterday)
    day_before_value = series.get(day_before)

    avg_7d = _average_window(series, start=reference - timedelta(days=7), end=reference)
    avg_14d = _average_window(series, start=reference - timedelta(days=14), end=reference)
    avg_28d = _average_window(series, start=reference - timedelta(days=28), end=reference)
    avg_90d = _average_window(series, start=reference - timedelta(days=90), end=reference)

    return {
        "yesterday_value": yesterday_value,
        "day_before_value": day_before_value,
        "avg_7d": avg_7d,
        "avg_14d": avg_14d,
        "avg_28d": avg_28d,
        "avg_90d": avg_90d,
    }


def _calculate_changes(
    averages: Mapping[str, Optional[float]],
) -> Dict[str, Optional[float]]:
    yesterday_value = averages.get("yesterday_value")
    day_before_value = averages.get("day_before_value")
    avg_7d = averages.get("avg_7d")
    avg_28d = averages.get("avg_28d")

    abs_change_d1: Optional[float] = None
    pct_change_d1: Optional[float] = None
    if yesterday_value is not None and day_before_value is not None:
        abs_change_d1 = yesterday_value - day_before_value
        if day_before_value:
            pct_change_d1 = (abs_change_d1 / day_before_value) * 100.0

    abs_change_7d: Optional[float] = None
    pct_change_7d: Optional[float] = None
    if avg_7d is not None and avg_28d is not None:
        abs_change_7d = avg_7d - avg_28d
        if avg_28d:
            pct_change_7d = (abs_change_7d / avg_28d) * 100.0

    return {
        "abs_change_d1": abs_change_d1,
        "pct_change_d1": pct_change_d1,
        "abs_change_7d": abs_change_7d,
        "pct_change_7d": pct_change_7d,
    }


def _find_historical_extremes(
    series: Dict[date, Optional[float]], *, reference: date
) -> Dict[str, Optional[float]]:
    six_month_high = _extreme_window(
        series, start=reference - timedelta(days=182), end=reference, reducer=max
    )
    six_month_low = _extreme_window(
        series, start=reference - timedelta(days=182), end=reference, reducer=min
    )
    three_month_high = _extreme_window(
        series, start=reference - timedelta(days=91), end=reference, reducer=max
    )
    three_month_low = _extreme_window(
        series, start=reference - timedelta(days=91), end=reference, reducer=min
    )
    all_time_high = _extreme_window(series, reducer=max)
    all_time_low = _extreme_window(series, reducer=min)

    return {
        "six_month_high": six_month_high,
        "six_month_low": six_month_low,
        "three_month_high": three_month_high,
        "three_month_low": three_month_low,
        "all_time_high": all_time_high,
        "all_time_low": all_time_low,
    }


def _build_metric_stats(series: Dict[date, Optional[float]], *, reference: date) -> Dict[str, Optional[float]]:
    averages = _calculate_moving_averages(series, reference=reference)
    changes = _calculate_changes(averages)
    extremes = _find_historical_extremes(series, reference=reference)

    stats: Dict[str, Optional[float]] = {
        "yesterday_value": averages.get("yesterday_value"),
        "day_before_value": averages.get("day_before_value"),
        "avg_7d": averages.get("avg_7d"),
        "avg_14d": averages.get("avg_14d"),
        "avg_28d": averages.get("avg_28d"),
        "abs_change_d1": changes.get("abs_change_d1"),
        "pct_change_d1": changes.get("pct_change_d1"),
        "abs_change_7d": changes.get("abs_change_7d"),
        "pct_change_7d": changes.get("pct_change_7d"),
        "moving_avg_7d": averages.get("avg_7d"),
        "moving_avg_28d": averages.get("avg_28d"),
        "moving_avg_90d": averages.get("avg_90d"),
    }

    stats.update(extremes)

    for key, value in list(stats.items()):
        stats[key] = converters.to_float(value)
    return stats


_METRIC_SPECS: Dict[str, tuple[str, Optional[Callable[[Any], Optional[float]]]]] = {
    "weight": ("weight_kg", None),
    "weight_kg": ("weight_kg", None),
    "body_fat_pct": ("body_fat_pct", None),
    "muscle_pct": ("muscle_pct", None),
    "water_pct": ("water_pct", None),
    "body_age_years": ("body_age_years", None),
    "body_age_delta_years": ("body_age_delta_years", None),
    "resting_heart_rate": ("hr_resting", None),
    "hr_resting": ("hr_resting", None),
    "hr_avg": ("hr_avg", None),
    "hr_max": ("hr_max", None),
    "hr_min": ("hr_min", None),
    "cardio_recovery": ("cardio_recovery", None),
    "respiratory_rate": ("respiratory_rate", None),
    "walking_hr_avg": ("walking_hr_avg", None),
    "blood_oxygen_saturation": ("blood_oxygen_saturation", None),
    "wrist_temperature": ("wrist_temperature", None),
    "hrv_sdnn_ms": ("hrv_sdnn_ms", None),
    "vo2_max": ("vo2_max", None),
    "steps": ("steps", None),
    "distance_m": ("distance_m", None),
    "flights_climbed": ("flights_climbed", None),
    "exercise_minutes": ("exercise_minutes", None),
    "stand_minutes": ("stand_minutes", None),
    "time_in_daylight": ("time_in_daylight", None),
    "calories_active": ("calories_active", None),
    "calories_resting": ("calories_resting", None),
    "strength_volume": ("strength_volume_kg", None),
    "strength_volume_kg": ("strength_volume_kg", None),
    "sleep_hours": ("sleep_total_minutes", converters.minutes_to_hours),
    "sleep_total_minutes": ("sleep_total_minutes", None),
    "sleep_asleep_minutes": ("sleep_asleep_minutes", None),
    "sleep_rem_minutes": ("sleep_rem_minutes", None),
    "sleep_deep_minutes": ("sleep_deep_minutes", None),
    "sleep_core_minutes": ("sleep_core_minutes", None),
    "sleep_awake_minutes": ("sleep_awake_minutes", None)
}


def get_metrics_overview(
    dal: DataAccessLayer,
    *,
    reference_date: Optional[date] = None,
) -> Dict[str, Dict[str, Any]]:
    """Return derived metrics keyed by metric name using daily_summary history."""
    reference = reference_date or date.today()
    history_fn = getattr(dal, "get_historical_data", None)
    if not callable(history_fn):
        log_utils.log_message(
            "DataAccessLayer does not expose get_historical_data; metrics overview unavailable.",
            "WARN",
        )
        return {}

    start_date = date(2000, 1, 1)
    if reference <= start_date:
        start_date = reference - timedelta(days=365)

    try:
        rows = history_fn(start_date, reference)
    except Exception as exc:
        log_utils.log_message(f"Failed to load daily_summary history: {exc}", "ERROR")
        return {}

    if not rows:
        return {}

    if not isinstance(rows, list):
        rows = list(rows)

    metrics: Dict[str, Dict[str, Any]] = {}
    for name, (column, transform) in _METRIC_SPECS.items():
        try:
            series = _build_metric_series(rows, column, transform)
            if not series:
                continue
            stats = _build_metric_stats(series, reference=reference)
        except Exception as exc:
            log_utils.log_message(f"Failed to compute metric '{name}': {exc}", "WARN")
            continue

        if any(value is not None for value in stats.values()):
            stats["metric_name"] = name
            metrics[name] = stats

    return metrics
