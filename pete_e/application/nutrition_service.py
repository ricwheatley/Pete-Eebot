"""Application service for approximate nutrition logging."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Mapping

from pete_e.application.exceptions import BadRequestError, DataAccessError
from pete_e.config import settings
from pete_e.domain.nutrition import NutritionValidationError, build_nutrition_log_record
from pete_e.utils import converters


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _parse_iso_date(value: str, field: str = "date") -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise BadRequestError(f"Invalid date value for '{field}': {value}", code="invalid_date") from exc


class NutritionService:
    """Use cases for storing and reading GPT-supplied macro estimates."""

    def __init__(self, dal: Any, *, timezone_name: str | None = None):
        self._dal = dal
        self._timezone_name = timezone_name or getattr(settings, "USER_TIMEZONE", "Europe/London")

    def log_macros(self, payload: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        try:
            record = build_nutrition_log_record(
                payload,
                timezone_name=self._timezone_name,
                now=now,
            )
        except NutritionValidationError as exc:
            raise BadRequestError(str(exc), code="invalid_nutrition_payload") from exc

        try:
            row, duplicate = self._dal.insert_nutrition_log(record.as_insert_dict())
        except Exception as exc:
            raise DataAccessError("Failed to persist nutrition log.") from exc

        return self._shape_log_row(row, duplicate=duplicate, warnings=record.warnings)

    def daily_summary(self, iso_date: str) -> dict[str, Any]:
        target_date = _parse_iso_date(iso_date)
        try:
            summary = self._dal.get_nutrition_daily_summary(target_date)
        except Exception as exc:
            raise DataAccessError("Failed to load nutrition daily summary.") from exc
        return _shape_daily_summary(summary, target_date=target_date)

    @staticmethod
    def _shape_log_row(
        row: Mapping[str, Any],
        *,
        duplicate: bool,
        warnings: tuple[str, ...],
    ) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "eaten_at": _json_safe(row.get("eaten_at")),
            "local_date": _json_safe(row.get("local_date")),
            "protein_g": _json_safe(row.get("protein_g")),
            "carbs_g": _json_safe(row.get("carbs_g")),
            "fat_g": _json_safe(row.get("fat_g")),
            "alcohol_g": _json_safe(row.get("alcohol_g")),
            "fiber_g": _json_safe(row.get("fiber_g")),
            "estimated_total_calories": _json_safe(row.get("estimated_total_calories")),
            "calories_est": _json_safe(row.get("calories_est")),
            "source": row.get("source"),
            "context": row.get("context"),
            "confidence": row.get("confidence"),
            "meal_label": row.get("meal_label"),
            "notes": row.get("notes"),
            "client_event_id": row.get("client_event_id"),
            "duplicate": bool(duplicate),
            "warnings": list(warnings),
        }


def _shape_daily_summary(summary: Mapping[str, Any] | None, *, target_date: date) -> dict[str, Any]:
    row = dict(summary or {})
    meals_logged = int(row.get("meals_logged") or 0)
    source_breakdown = row.get("source_breakdown") or {}
    confidence_breakdown = row.get("confidence_breakdown") or {}
    status = "observed" if meals_logged else "missing"

    return {
        "date": target_date.isoformat(),
        "total_protein_g": _json_safe(row.get("protein_g") or 0),
        "total_carbs_g": _json_safe(row.get("carbs_g") or 0),
        "total_fat_g": _json_safe(row.get("fat_g") or 0),
        "total_alcohol_g": _json_safe(row.get("alcohol_g") or 0),
        "total_fiber_g": _json_safe(row.get("fiber_g") or 0),
        "total_estimated_calories": _json_safe(row.get("calories_est") or 0),
        "meals_logged": meals_logged,
        "source_breakdown": _json_safe(source_breakdown),
        "confidence_breakdown": _json_safe(confidence_breakdown),
        "data_quality": {
            "status": status,
            "nutrition_data_quality": "partial" if meals_logged else "missing",
            "is_estimated": True,
            "last_logged_at": _json_safe(row.get("last_logged_at")),
        },
    }


def build_nutrition_context(dal: Any, *, target_date: date) -> dict[str, Any]:
    """Return compact nutrition trend context for coach-state payloads."""

    getter = getattr(dal, "get_nutrition_daily_summaries", None)
    if not callable(getter):
        return {
            "window": {
                "start_date": (target_date - timedelta(days=6)).isoformat(),
                "end_date": target_date.isoformat(),
                "days": 7,
            },
            "last_7d": _empty_window_summary(),
            "prev_7d": _empty_window_summary(),
            "data_quality": {
                "status": "not_configured",
                "nutrition_data_quality": "missing",
                "logging_days_last_7d": 0,
            },
        }

    start = target_date - timedelta(days=13)
    try:
        rows = list(getter(start, target_date) or [])
    except Exception:
        return {
            "window": {
                "start_date": (target_date - timedelta(days=6)).isoformat(),
                "end_date": target_date.isoformat(),
                "days": 7,
            },
            "last_7d": _empty_window_summary(),
            "prev_7d": _empty_window_summary(),
            "data_quality": {
                "status": "unavailable",
                "nutrition_data_quality": "missing",
                "logging_days_last_7d": 0,
            },
        }

    last_7 = _filter_summaries(rows, target_date - timedelta(days=6), target_date)
    prev_7 = _filter_summaries(rows, target_date - timedelta(days=13), target_date - timedelta(days=7))
    last_summary = _window_summary(last_7)
    prev_summary = _window_summary(prev_7)
    logging_days = int(last_summary["logging_days"])
    quality = "missing"
    if logging_days >= 5:
        quality = "observed"
    elif logging_days > 0:
        quality = "partial"

    return {
        "window": {
            "start_date": (target_date - timedelta(days=6)).isoformat(),
            "end_date": target_date.isoformat(),
            "days": 7,
        },
        "last_7d": _json_safe(last_summary),
        "prev_7d": _json_safe(prev_summary),
        "data_quality": {
            "status": quality,
            "nutrition_data_quality": quality,
            "logging_days_last_7d": logging_days,
            "estimated_values": True,
        },
        "coaching_note": "Use nutrition estimates as trend context, not exact calorie accounting.",
    }


def _filter_summaries(rows: list[Mapping[str, Any]], start: date, end: date) -> list[Mapping[str, Any]]:
    selected: list[Mapping[str, Any]] = []
    for row in rows:
        row_date = converters.to_date(row.get("date") or row.get("local_date"))
        if row_date is not None and start <= row_date <= end:
            selected.append(row)
    return selected


def _empty_window_summary() -> dict[str, Any]:
    return {
        "logging_days": 0,
        "meals_logged": 0,
        "protein_g_avg": None,
        "carbs_g_avg": None,
        "fat_g_avg": None,
        "avg_alcohol_g": None,
        "avg_fiber_g": None,
        "avg_estimated_calories": None,
    }


def _window_summary(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    logged_rows = [row for row in rows if int(row.get("meals_logged") or 0) > 0]
    if not logged_rows:
        return _empty_window_summary()
    return {
        "logging_days": len(logged_rows),
        "meals_logged": sum(int(row.get("meals_logged") or 0) for row in logged_rows),
        "protein_g_avg": _avg(logged_rows, "protein_g"),
        "carbs_g_avg": _avg(logged_rows, "carbs_g"),
        "fat_g_avg": _avg(logged_rows, "fat_g"),
        "avg_alcohol_g": _avg(logged_rows, "alcohol_g"),
        "avg_fiber_g": _avg(logged_rows, "fiber_g"),
        "avg_estimated_calories": _avg(logged_rows, "calories_est"),
    }


def _avg(rows: list[Mapping[str, Any]], field: str) -> float | None:
    values: list[float] = []
    for row in rows:
        value = converters.to_float(row.get(field))
        if value is not None:
            values.append(value)
    return (sum(values) / len(values)) if values else None
