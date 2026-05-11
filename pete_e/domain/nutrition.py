"""Domain helpers for approximate nutrition logging."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_SOURCE = "photo_estimate"
DEFAULT_CONFIDENCE = "medium"
ALLOWED_CONFIDENCE = {"low", "medium", "high"}
DEFAULT_TIMEZONE = "Europe/London"

_GRAM_QUANT = Decimal("0.01")
_CALORIE_QUANT = Decimal("0.01")
_MAX_GRAMS = Decimal("500.00")
_MAX_CALORIES = Decimal("5000.00")


class NutritionValidationError(ValueError):
    """Raised when an incoming nutrition payload cannot be accepted."""


@dataclass(frozen=True)
class NutritionLogRecord:
    """Canonical immutable nutrition event ready for persistence."""

    client_event_id: str | None
    dedupe_fingerprint: str
    eaten_at: datetime
    local_date: date
    protein_g: Decimal
    carbs_g: Decimal
    fat_g: Decimal
    alcohol_g: Decimal | None
    fiber_g: Decimal | None
    estimated_total_calories: Decimal | None
    calories_est: Decimal
    source: str
    context: str | None
    confidence: str
    meal_label: str | None
    notes: str | None
    raw_payload_json: Mapping[str, Any]
    warnings: tuple[str, ...] = ()

    def as_insert_dict(self) -> dict[str, Any]:
        return {
            "client_event_id": self.client_event_id,
            "dedupe_fingerprint": self.dedupe_fingerprint,
            "eaten_at": self.eaten_at,
            "local_date": self.local_date,
            "protein_g": self.protein_g,
            "carbs_g": self.carbs_g,
            "fat_g": self.fat_g,
            "alcohol_g": self.alcohol_g,
            "fiber_g": self.fiber_g,
            "estimated_total_calories": self.estimated_total_calories,
            "calories_est": self.calories_est,
            "source": self.source,
            "context": self.context,
            "confidence": self.confidence,
            "meal_label": self.meal_label,
            "notes": self.notes,
            "raw_payload_json": dict(self.raw_payload_json),
        }


def build_nutrition_log_record(
    payload: Mapping[str, Any],
    *,
    timezone_name: str = DEFAULT_TIMEZONE,
    now: datetime | None = None,
) -> NutritionLogRecord:
    """Validate and normalize a GPT-supplied approximate macro payload."""

    if not isinstance(payload, Mapping):
        raise NutritionValidationError("Nutrition payload must be a JSON object.")

    tz = _resolve_timezone(timezone_name)
    protein = _macro_decimal(payload.get("protein_g"), "protein_g")
    carbs = _macro_decimal(payload.get("carbs_g"), "carbs_g")
    fat = _macro_decimal(payload.get("fat_g"), "fat_g")
    alcohol = _optional_macro_decimal(payload.get("alcohol_g"), "alcohol_g")
    fiber = _optional_macro_decimal(payload.get("fiber_g"), "fiber_g")
    estimated_total_calories = _optional_calorie_decimal(
        payload.get("estimated_total_calories"), "estimated_total_calories"
    )
    if protein == 0 and carbs == 0 and fat == 0:
        raise NutritionValidationError("At least one macro value must be greater than zero.")

    calories = estimated_total_calories or _estimate_calories(
        protein_g=protein, carbs_g=carbs, fat_g=fat, alcohol_g=alcohol
    )
    if calories > _MAX_CALORIES:
        raise NutritionValidationError("Estimated calories exceed the per-entry safety limit.")

    source = _clean_token(payload.get("source"), DEFAULT_SOURCE, "source")
    confidence = _clean_token(payload.get("confidence"), DEFAULT_CONFIDENCE, "confidence").lower()
    if confidence not in ALLOWED_CONFIDENCE:
        raise NutritionValidationError("confidence must be one of: low, medium, high.")

    eaten_at = _parse_timestamp(payload.get("timestamp"), tz=tz, now=now)
    local_date = eaten_at.astimezone(tz).date()
    context = _optional_text(payload.get("context"), "context", max_length=80)
    meal_label = _optional_text(payload.get("meal_label"), "meal_label", max_length=80)
    notes = _optional_text(payload.get("notes"), "notes", max_length=500)
    client_event_id = _optional_text(payload.get("client_event_id"), "client_event_id", max_length=120)
    warnings = _warnings(protein=protein, carbs=carbs, fat=fat, calories=calories)
    fingerprint = _dedupe_fingerprint(
        eaten_at=eaten_at,
        protein=protein,
        carbs=carbs,
        fat=fat,
        source=source,
        context=context,
    )

    return NutritionLogRecord(
        client_event_id=client_event_id,
        dedupe_fingerprint=fingerprint,
        eaten_at=eaten_at,
        local_date=local_date,
        protein_g=protein,
        carbs_g=carbs,
        fat_g=fat,
        alcohol_g=alcohol,
        fiber_g=fiber,
        estimated_total_calories=estimated_total_calories,
        calories_est=calories,
        source=source,
        context=context,
        confidence=confidence,
        meal_label=meal_label,
        notes=notes,
        raw_payload_json=dict(payload),
        warnings=tuple(warnings),
    )


def _resolve_timezone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name or DEFAULT_TIMEZONE)
    except ZoneInfoNotFoundError as exc:
        raise NutritionValidationError(f"Unknown timezone: {timezone_name}") from exc


def _macro_decimal(value: Any, field: str) -> Decimal:
    if value is None:
        raise NutritionValidationError(f"{field} is required.")
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise NutritionValidationError(f"{field} must be a number.") from exc
    if not decimal.is_finite():
        raise NutritionValidationError(f"{field} must be a finite number.")
    if decimal < 0:
        raise NutritionValidationError(f"{field} cannot be negative.")
    if decimal > _MAX_GRAMS:
        raise NutritionValidationError(f"{field} exceeds the per-entry safety limit.")
    return decimal.quantize(_GRAM_QUANT, rounding=ROUND_HALF_UP)


def _estimate_calories(*, protein_g: Decimal, carbs_g: Decimal, fat_g: Decimal, alcohol_g: Decimal | None) -> Decimal:
    calories = protein_g * Decimal("4") + carbs_g * Decimal("4") + fat_g * Decimal("9")
    if alcohol_g is not None:
        calories += alcohol_g * Decimal("7")
    return calories.quantize(_CALORIE_QUANT, rounding=ROUND_HALF_UP)


def _optional_macro_decimal(value: Any, field: str) -> Decimal | None:
    if value is None:
        return None
    return _macro_decimal(value, field)


def _optional_calorie_decimal(value: Any, field: str) -> Decimal | None:
    if value is None:
        return None
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise NutritionValidationError(f"{field} must be a number.") from exc
    if not decimal.is_finite():
        raise NutritionValidationError(f"{field} must be a finite number.")
    if decimal < 0:
        raise NutritionValidationError(f"{field} cannot be negative.")
    if decimal > _MAX_CALORIES:
        raise NutritionValidationError(f"{field} exceeds the per-entry safety limit.")
    return decimal.quantize(_CALORIE_QUANT, rounding=ROUND_HALF_UP)


def _parse_timestamp(value: Any, *, tz: ZoneInfo, now: datetime | None) -> datetime:
    if value in (None, ""):
        resolved = now or datetime.now(tz)
    elif isinstance(value, datetime):
        resolved = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            resolved = datetime.fromisoformat(text)
        except ValueError as exc:
            raise NutritionValidationError("timestamp must be an ISO-8601 datetime.") from exc
    else:
        raise NutritionValidationError("timestamp must be an ISO-8601 datetime.")

    if resolved.tzinfo is None:
        resolved = resolved.replace(tzinfo=tz)
    return resolved.astimezone(timezone.utc)


def _clean_token(value: Any, default: str, field: str) -> str:
    if value in (None, ""):
        return default
    text = str(value).strip()
    if not text:
        return default
    if len(text) > 80:
        raise NutritionValidationError(f"{field} must be 80 characters or fewer.")
    return text


def _optional_text(value: Any, field: str, *, max_length: int) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > max_length:
        raise NutritionValidationError(f"{field} must be {max_length} characters or fewer.")
    return text


def _warnings(*, protein: Decimal, carbs: Decimal, fat: Decimal, calories: Decimal) -> list[str]:
    warnings: list[str] = []
    if protein >= Decimal("80"):
        warnings.append("high_protein_single_entry")
    if carbs >= Decimal("180"):
        warnings.append("high_carbs_single_entry")
    if fat >= Decimal("90"):
        warnings.append("high_fat_single_entry")
    if calories >= Decimal("2000"):
        warnings.append("high_calorie_single_entry")
    return warnings


def _dedupe_fingerprint(
    *,
    eaten_at: datetime,
    protein: Decimal,
    carbs: Decimal,
    fat: Decimal,
    source: str,
    context: str | None,
) -> str:
    canonical = {
        "eaten_at_utc": eaten_at.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "protein_g": str(protein),
        "carbs_g": str(carbs),
        "fat_g": str(fat),
        "source": source,
        "context": context or "",
    }
    body = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
