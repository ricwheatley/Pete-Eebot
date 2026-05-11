"""Application service for approximate nutrition logging."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Mapping

from pete_e.application.exceptions import BadRequestError, DataAccessError, NotFoundError
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


    def update_log(self, log_id: int, payload: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        if not isinstance(log_id, int) or log_id <= 0:
            raise BadRequestError("Invalid nutrition log id.", code="invalid_nutrition_log_id")
        try:
            patch = _validate_update_payload(payload, timezone_name=self._timezone_name, now=now)
        except NutritionValidationError as exc:
            raise BadRequestError(str(exc), code="invalid_nutrition_payload") from exc
        try:
            row = self._dal.update_nutrition_log(log_id, patch)
        except KeyError as exc:
            raise NotFoundError("Nutrition log not found.", code="nutrition_log_not_found") from exc
        except Exception as exc:
            raise DataAccessError("Failed to update nutrition log.") from exc

        refresher = getattr(self._dal, "refresh_daily_summary_range", None)
        if callable(refresher):
            try:
                refresher(row.get("local_date"), row.get("previous_local_date"))
            except Exception:
                pass

        return self._shape_log_row(row, duplicate=False, warnings=())

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


def _validate_update_payload(payload: Mapping[str, Any], *, timezone_name: str, now: datetime | None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise BadRequestError("Nutrition payload must be a JSON object.", code="invalid_nutrition_payload")

    editable = {
        "protein_g", "carbs_g", "fat_g", "alcohol_g", "fiber_g",
        "estimated_total_calories", "source", "context", "confidence",
        "meal_label", "notes", "timestamp", "eaten_at"
    }
    patch: dict[str, Any] = {}
    unknown = set(payload.keys()) - editable
    if unknown:
        raise BadRequestError(f"Unsupported fields for nutrition update: {', '.join(sorted(unknown))}", code="invalid_nutrition_payload")

    from pete_e.domain import nutrition as n
    for field in ("protein_g", "carbs_g", "fat_g", "alcohol_g", "fiber_g"):
        if field in payload:
            value = payload[field]
            patch[field] = None if value is None else n._macro_decimal(value, field)

    if "estimated_total_calories" in payload:
        value = payload["estimated_total_calories"]
        patch["estimated_total_calories"] = None if value is None else n._optional_calorie_decimal(value, "estimated_total_calories")

    if "confidence" in payload:
        value = n._clean_token(payload.get("confidence"), n.DEFAULT_CONFIDENCE, "confidence").lower()
        if value not in n.ALLOWED_CONFIDENCE:
            raise BadRequestError("confidence must be one of: low, medium, high.", code="invalid_nutrition_payload")
        patch["confidence"] = value

    text_map = {"source": ("source", 80), "context": ("context", 80), "meal_label": ("meal_label", 80), "notes": ("notes", 500)}
    for field, (name, max_len) in text_map.items():
        if field in payload:
            val = payload[field]
            if val is None:
                patch[field] = None
            elif field == "source":
                patch[field] = n._clean_token(val, n.DEFAULT_SOURCE, name)
            else:
                patch[field] = n._optional_text(val, name, max_length=max_len)

    ts = payload.get("timestamp") if "timestamp" in payload else payload.get("eaten_at") if "eaten_at" in payload else ...
    if ts is not ...:
        tz = n._resolve_timezone(timezone_name)
        eaten_at = n._parse_timestamp(ts, tz=tz, now=now)
        patch["eaten_at"] = eaten_at
        patch["local_date"] = eaten_at.astimezone(tz).date()

    return patch
