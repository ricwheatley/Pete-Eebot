"""Infrastructure implementation for importing performed wger workout sets."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from pete_e.config import settings
from pete_e.domain.wger_workouts import (
    WgerWorkoutImportSummary,
    WgerWorkoutIngestResult,
    WgerWorkoutRepository,
    WgerWorkoutSet,
)
from pete_e.infrastructure import log_utils
from pete_e.infrastructure.wger_client import WgerClient


_POUNDS_TO_KILOGRAMS = Decimal("0.45359237")
_WEIGHT_PRECISION = Decimal("0.001")


class WgerWorkoutValidationError(ValueError):
    """Raised when a complete wger response cannot be normalized safely."""


class WgerWorkoutLogIngestor:
    """Fetch and atomically reconcile an inclusive local-date window."""

    def __init__(
        self,
        *,
        repository: WgerWorkoutRepository,
        client: WgerClient,
        timezone_name: str | None = None,
    ) -> None:
        self._repository = repository
        self._client = client
        self._timezone_name = timezone_name or str(
            getattr(settings, "USER_TIMEZONE", "Europe/London")
        )
        self._timezone = ZoneInfo(self._timezone_name)

    def ingest(
        self,
        *,
        start_date: date,
        end_date: date,
        dry_run: bool = False,
    ) -> WgerWorkoutIngestResult:
        """Fetch, validate, and optionally reconcile the requested window."""

        try:
            return self._run_ingest(
                start_date=start_date,
                end_date=end_date,
                dry_run=dry_run,
            )
        except Exception as exc:  # noqa: BLE001 - source failures become retryable results
            message = self._safe_reason(exc)
            log_utils.error(f"Wger workout ingest failed: {message}")
            return WgerWorkoutIngestResult(
                success=False,
                failures=("Wger",),
                statuses={"Wger": "failed"},
                alerts=(f"Wger workout ingest failed: {message}",),
                error=message,
            )

    def _run_ingest(
        self,
        *,
        start_date: date,
        end_date: date,
        dry_run: bool,
    ) -> WgerWorkoutIngestResult:
        if start_date > end_date:
            raise WgerWorkoutValidationError("start date must be on or before end date")

        raw_logs = list(self._client.get_workout_logs(start_date, end_date) or [])
        unit_map = self._load_weight_unit_map(raw_logs)
        repetition_unit_map = self._load_repetition_unit_map(raw_logs)
        normalized: list[WgerWorkoutSet] = []
        skipped = 0
        source_ids: set[str] = set()

        for index, raw_log in enumerate(raw_logs):
            if not isinstance(raw_log, Mapping):
                raise WgerWorkoutValidationError(
                    f"workout log at index {index} is not an object"
                )
            workout_set = self._normalize_log(
                raw_log,
                unit_map=unit_map,
                repetition_unit_map=repetition_unit_map,
            )
            if workout_set is None or not (start_date <= workout_set.day <= end_date):
                skipped += 1
                continue
            if workout_set.source_id in source_ids:
                raise WgerWorkoutValidationError(
                    f"duplicate workout log id {workout_set.source_id}"
                )
            source_ids.add(workout_set.source_id)
            normalized.append(workout_set)

        normalized = self._assign_set_numbers(normalized)
        exercise_ids = sorted({item.exercise_id for item in normalized})

        if dry_run:
            self._repository.validate_wger_exercise_ids(exercise_ids)
            stored = 0
        else:
            stored = self._repository.reconcile_wger_logs(
                start_date=start_date,
                end_date=end_date,
                workout_sets=normalized,
            )

        summary = WgerWorkoutImportSummary(
            start_date=start_date,
            end_date=end_date,
            fetched=len(raw_logs),
            accepted=len(normalized),
            skipped=skipped,
            stored=stored,
            dry_run=dry_run,
        )
        result = WgerWorkoutIngestResult(
            success=True,
            summary=summary,
            statuses={"Wger": "dry-run" if dry_run else "ok"},
        )
        log_utils.info(result.summary_line())
        return result

    def _normalize_log(
        self,
        raw_log: Mapping[str, Any],
        *,
        unit_map: Mapping[str, str],
        repetition_unit_map: Mapping[str, str],
    ) -> WgerWorkoutSet | None:
        source_id = str(raw_log.get("id") or "").strip()
        if not source_id:
            raise WgerWorkoutValidationError("workout log is missing its source id")

        performed_at, local_day = self._parse_performed_at(raw_log.get("date"), source_id)

        raw_exercise_id = raw_log.get("exercise", raw_log.get("exercise_id"))
        try:
            exercise_id = int(raw_exercise_id)
        except (TypeError, ValueError) as exc:
            raise WgerWorkoutValidationError(
                f"workout log {source_id} has an invalid exercise id"
            ) from exc
        if exercise_id <= 0:
            raise WgerWorkoutValidationError(
                f"workout log {source_id} has an invalid exercise id"
            )

        raw_repetitions = raw_log.get("repetitions", raw_log.get("reps"))
        if raw_repetitions in (None, ""):
            return None
        repetition_unit_type = self._resolve_repetition_unit_type(
            raw_log.get("repetitions_unit", raw_log.get("repetition_unit")),
            repetition_unit_map,
        )
        if repetition_unit_type is None:
            raise WgerWorkoutValidationError(
                f"workout log {source_id} has an unknown repetition unit"
            )
        if repetition_unit_type != "REPETITIONS":
            return None
        repetitions = self._decimal(raw_repetitions, "repetitions", source_id)
        if repetitions <= 0:
            return None
        if repetitions != repetitions.to_integral_value():
            raise WgerWorkoutValidationError(
                f"workout log {source_id} has fractional repetitions"
            )

        weight_kg = self._normalize_weight(
            raw_log.get("weight"),
            raw_log.get("weight_unit"),
            unit_map=unit_map,
            source_id=source_id,
        )
        raw_rir = raw_log.get("rir")
        rir = None
        if raw_rir not in (None, ""):
            rir_decimal = self._decimal(raw_rir, "rir", source_id)
            if rir_decimal < 0 or rir_decimal > 10:
                raise WgerWorkoutValidationError(
                    f"workout log {source_id} has RIR outside 0-10"
                )
            rir = float(rir_decimal)

        raw_session_id = raw_log.get("session", raw_log.get("workout"))
        session_id = str(raw_session_id).strip() if raw_session_id is not None else None
        if session_id == "":
            session_id = None

        return WgerWorkoutSet(
            source_id=source_id,
            session_id=session_id,
            performed_at=performed_at,
            day=local_day,
            exercise_id=exercise_id,
            set_number=0,
            reps=int(repetitions),
            weight_kg=weight_kg,
            rir=rir,
        )

    def _parse_performed_at(self, raw_value: Any, source_id: str) -> tuple[datetime, date]:
        if isinstance(raw_value, datetime):
            parsed = raw_value
        elif isinstance(raw_value, date):
            parsed = datetime.combine(raw_value, time.min, tzinfo=self._timezone)
        elif isinstance(raw_value, str) and raw_value.strip():
            value = raw_value.strip()
            try:
                if "T" not in value and " " not in value:
                    parsed = datetime.combine(
                        date.fromisoformat(value),
                        time.min,
                        tzinfo=self._timezone,
                    )
                else:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise WgerWorkoutValidationError(
                    f"workout log {source_id} has an invalid date"
                ) from exc
        else:
            raise WgerWorkoutValidationError(
                f"workout log {source_id} is missing its date"
            )

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        localized = parsed.astimezone(self._timezone)
        return parsed.astimezone(timezone.utc), localized.date()

    def _normalize_weight(
        self,
        raw_weight: Any,
        raw_unit: Any,
        *,
        unit_map: Mapping[str, str],
        source_id: str,
    ) -> Decimal | None:
        if raw_weight in (None, ""):
            return None
        weight = self._decimal(raw_weight, "weight", source_id)
        if weight < 0:
            raise WgerWorkoutValidationError(
                f"workout log {source_id} has a negative weight"
            )
        if weight == 0:
            return Decimal("0")

        unit = self._resolve_unit(raw_unit, unit_map)
        if unit == "lb":
            weight *= _POUNDS_TO_KILOGRAMS
        elif unit != "kg":
            raise WgerWorkoutValidationError(
                f"workout log {source_id} has an unknown weight unit"
            )
        return weight.quantize(_WEIGHT_PRECISION)

    def _load_weight_unit_map(
        self,
        raw_logs: Sequence[Mapping[str, Any]],
    ) -> dict[str, str]:
        needs_lookup = any(
            self._unit_lookup_key(item.get("weight_unit")) is not None
            and self._unit_name(item.get("weight_unit")) is None
            and item.get("weight") not in (None, "", 0, "0", "0.00")
            for item in raw_logs
            if isinstance(item, Mapping)
        )
        if not needs_lookup:
            return {}

        units = list(self._client.get_weight_units() or [])
        mapped: dict[str, str] = {}
        for raw_unit in units:
            if not isinstance(raw_unit, Mapping):
                continue
            key = self._unit_lookup_key(raw_unit.get("id"))
            name = self._unit_name(raw_unit.get("name"))
            if key is not None and name is not None:
                mapped[key] = name
        return mapped

    def _load_repetition_unit_map(
        self,
        raw_logs: Sequence[Mapping[str, Any]],
    ) -> dict[str, str]:
        raw_units = [
            item.get("repetitions_unit", item.get("repetition_unit"))
            for item in raw_logs
            if isinstance(item, Mapping)
            and item.get("repetitions", item.get("reps")) not in (None, "")
        ]
        needs_lookup = any(
            self._unit_lookup_key(raw_unit) is not None
            and self._direct_repetition_unit_type(raw_unit) is None
            for raw_unit in raw_units
        )
        if not needs_lookup:
            return {}

        units = list(self._client.get_repetition_units() or [])
        mapped: dict[str, str] = {}
        for raw_unit in units:
            if not isinstance(raw_unit, Mapping):
                continue
            key = self._unit_lookup_key(raw_unit.get("id"))
            unit_type = self._direct_repetition_unit_type(raw_unit)
            if key is not None and unit_type is not None:
                mapped[key] = unit_type
        return mapped

    @classmethod
    def _resolve_repetition_unit_type(
        cls,
        raw_unit: Any,
        unit_map: Mapping[str, str],
    ) -> str | None:
        if raw_unit in (None, ""):
            return "REPETITIONS"
        direct = cls._direct_repetition_unit_type(raw_unit)
        if direct is not None:
            return direct
        if isinstance(raw_unit, Mapping):
            lookup = cls._unit_lookup_key(raw_unit.get("id"))
        else:
            lookup = cls._unit_lookup_key(raw_unit)
        return unit_map.get(lookup) if lookup is not None else None

    @classmethod
    def _direct_repetition_unit_type(cls, raw_unit: Any) -> str | None:
        if isinstance(raw_unit, Mapping):
            raw_type = raw_unit.get("unit_type")
            if isinstance(raw_type, str):
                normalized_type = raw_type.strip().upper()
                if normalized_type in {"REPETITIONS", "TIME", "DISTANCE"}:
                    return normalized_type
            raw_unit = raw_unit.get("name")
        if not isinstance(raw_unit, str) or raw_unit.strip().isdigit():
            return None
        normalized = raw_unit.strip().lower()
        if normalized in {"rep", "reps", "repetition", "repetitions"}:
            return "REPETITIONS"
        if normalized in {"s", "sec", "second", "seconds", "min", "minute", "minutes"}:
            return "TIME"
        if normalized in {"m", "meter", "meters", "km", "kilometer", "kilometers"}:
            return "DISTANCE"
        return None

    @classmethod
    def _resolve_unit(cls, raw_unit: Any, unit_map: Mapping[str, str]) -> str | None:
        direct = cls._unit_name(raw_unit)
        if direct is not None:
            return direct
        if isinstance(raw_unit, Mapping):
            direct = cls._unit_name(raw_unit.get("name"))
            if direct is not None:
                return direct
            lookup = cls._unit_lookup_key(raw_unit.get("id"))
        else:
            lookup = cls._unit_lookup_key(raw_unit)
        return unit_map.get(lookup) if lookup is not None else None

    @staticmethod
    def _unit_lookup_key(raw_unit: Any) -> str | None:
        if isinstance(raw_unit, Mapping):
            raw_unit = raw_unit.get("id")
        if isinstance(raw_unit, int):
            return str(raw_unit)
        if isinstance(raw_unit, str) and raw_unit.strip().isdigit():
            return str(int(raw_unit.strip()))
        return None

    @staticmethod
    def _unit_name(raw_unit: Any) -> str | None:
        if isinstance(raw_unit, Mapping):
            raw_unit = raw_unit.get("name")
        if not isinstance(raw_unit, str):
            return None
        normalized = raw_unit.strip().lower()
        if normalized in {"kg", "kilogram", "kilograms"}:
            return "kg"
        if normalized in {"lb", "lbs", "pound", "pounds"}:
            return "lb"
        return None

    @staticmethod
    def _decimal(raw_value: Any, field: str, source_id: str) -> Decimal:
        try:
            value = Decimal(str(raw_value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise WgerWorkoutValidationError(
                f"workout log {source_id} has an invalid {field}"
            ) from exc
        if not value.is_finite():
            raise WgerWorkoutValidationError(
                f"workout log {source_id} has an invalid {field}"
            )
        return value

    @staticmethod
    def _assign_set_numbers(workout_sets: Sequence[WgerWorkoutSet]) -> list[WgerWorkoutSet]:
        ordered = sorted(
            workout_sets,
            key=lambda item: (
                item.day,
                item.exercise_id,
                item.performed_at,
                item.session_id or "",
                item.source_id,
            ),
        )
        counters: dict[tuple[date, int], int] = {}
        numbered: list[WgerWorkoutSet] = []
        for item in ordered:
            key = (item.day, item.exercise_id)
            set_number = counters.get(key, 0) + 1
            counters[key] = set_number
            numbered.append(replace(item, set_number=set_number))
        return numbered

    @staticmethod
    def _safe_reason(exc: BaseException) -> str:
        reason = str(exc).strip()
        return reason or exc.__class__.__name__


__all__ = [
    "WgerWorkoutLogIngestor",
    "WgerWorkoutValidationError",
]
