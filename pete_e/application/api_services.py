"""Application services powering the public API endpoints."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict

from pete_e.config import settings
from pete_e.infrastructure.postgres_dal import PostgresDal
from pete_e.application.plan_read_model import PlanReadModel
from pete_e.utils import converters
from pete_e.utils.coercion import coerce_numeric


_METRIC_UNITS = {
    "weight_kg": "kg",
    "body_fat_pct": "%",
    "muscle_pct": "%",
    "water_pct": "%",
    "fat_free_mass_kg": "kg",
    "fat_mass_kg": "kg",
    "muscle_mass_kg": "kg",
    "water_mass_kg": "kg",
    "bone_mass_kg": "kg",
    "bmr_kcal_day": "kcal/day",
    "steps": "count",
    "exercise_minutes": "min",
    "calories_active": "kcal",
    "calories_resting": "kcal",
    "stand_minutes": "min",
    "distance_m": "m",
    "flights_climbed": "count",
    "respiratory_rate": "breaths/min",
    "walking_hr_avg": "bpm",
    "blood_oxygen_saturation": "%",
    "wrist_temperature": "degC",
    "time_in_daylight": "min",
    "cardio_recovery": "bpm",
    "hr_resting": "bpm",
    "hrv_sdnn_ms": "ms",
    "vo2_max": "ml/kg/min",
    "hr_avg": "bpm",
    "hr_max": "bpm",
    "hr_min": "bpm",
    "sleep_total_minutes": "min",
    "sleep_asleep_minutes": "min",
    "sleep_rem_minutes": "min",
    "sleep_deep_minutes": "min",
    "sleep_core_minutes": "min",
    "sleep_awake_minutes": "min",
    "body_age_years": "years",
    "body_age_delta_years": "years",
    "strength_volume_kg": "kg",
}

_PRIMARY_FIELDS = (
    "weight_kg",
    "sleep_asleep_minutes",
    "hr_resting",
    "hrv_sdnn_ms",
    "strength_volume_kg",
)

_LOW_TRUST_FIELDS = {
    "body_fat_pct",
    "muscle_pct",
    "water_pct",
    "body_age_years",
    "body_age_delta_years",
    "calories_active",
    "calories_resting",
    "vo2_max",
}

_MODERATE_TRUST_FIELDS = {"steps", "stand_minutes", "flights_climbed", "time_in_daylight"}


def _metric_trust_level(metric_key: str) -> str:
    if metric_key in _LOW_TRUST_FIELDS:
        return "low"
    if metric_key in _MODERATE_TRUST_FIELDS:
        return "moderate"
    return "high"
    """Perform metric trust level."""


def _metric_source(metric_key: str) -> str:
    if metric_key in {"weight_kg", "body_fat_pct", "muscle_pct", "water_pct", "body_age_years"}:
        return "withings_or_body_age"
    if metric_key == "strength_volume_kg":
        return "wger_logs"
    return "apple_health"
    """Perform metric source."""


def _window_payload(*, end_date: date, days: int) -> dict[str, Any]:
    return {
        "start_date": (end_date - timedelta(days=days - 1)).isoformat(),
        "end_date": end_date.isoformat(),
        "days": days,
    }
    """Perform window payload."""


def _shape_metric_entry(metric_key: str, raw_value: Any) -> dict[str, Any]:
    value = _json_safe(coerce_numeric(raw_value))
    return {
        "value": value,
        "unit": _METRIC_UNITS.get(metric_key),
        "source": _metric_source(metric_key),
        "trust_level": _metric_trust_level(metric_key),
        "is_imputed": False,
        "data_quality": "missing" if value is None else "observed",
    }
    """Perform shape metric entry."""



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
    """Perform json safe."""


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None
    """Perform avg."""


def _window_rows(rows: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in rows:
        row_date = converters.to_date(row.get("date"))
        if row_date is not None and start <= row_date <= end:
            selected.append(row)
    return selected
    """Perform window rows."""


def _numeric_values(rows: list[dict[str, Any]], field: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = converters.to_float(row.get(field))
        if value is not None:
            values.append(value)
    return values
    """Perform numeric values."""


def _sum_field(rows: list[dict[str, Any]], field: str) -> float | None:
    values = _numeric_values(rows, field)
    return sum(values) if values else None
    """Perform sum field."""


class _DateParserMixin:
    """Shared helpers for services that accept ISO date strings."""

    @staticmethod
    def _parse_iso_date(value: str, field: str) -> date:
        try:
            return date.fromisoformat(value)
        except ValueError as exc:  # pragma: no cover - defensive re-raise
            raise ValueError(f"Invalid date value for '{field}': {value}") from exc
        """Perform parse iso date."""


class MetricsService(_DateParserMixin):
    """Read-only service exposing metrics related stored procedures."""

    def __init__(self, dal: PostgresDal):
        self._dal = dal
        """Initialize this object."""

    def overview(self, iso_date: str) -> Dict[str, Any]:
        target_date = self._parse_iso_date(iso_date, "date")
        columns, rows = self._dal.get_metrics_overview(target_date)
        return {"columns": columns, "rows": rows}
        """Perform overview."""

    def daily_summary(self, iso_date: str) -> Dict[str, Any]:
        target_date = self._parse_iso_date(iso_date, "date")
        row = self._dal.get_daily_summary(target_date)
        if not row:
            return {
                "date": target_date.isoformat(),
                "metrics": {},
                "data_quality": {
                    "status": "missing",
                    "completeness_pct": 0.0,
                    "missing_fields": list(_PRIMARY_FIELDS),
                },
            }

        metrics: Dict[str, Any] = {}
        missing: list[str] = []
        for key, raw_value in row.items():
            if key == "date":
                continue
            metric_entry = _shape_metric_entry(key, raw_value)
            if key in _PRIMARY_FIELDS and metric_entry["value"] is None:
                missing.append(key)
            metrics[key] = metric_entry

        completeness = self._completeness_pct([row], _PRIMARY_FIELDS)
        return {
            "date": target_date.isoformat(),
            "metrics": metrics,
            "data_quality": {
                "status": "complete" if not missing else "partial",
                "completeness_pct": completeness,
                "missing_fields": missing,
            },
        }
        """Perform daily summary."""

    def recent_workouts(self, days: int = 14, iso_end_date: str | None = None) -> Dict[str, Any]:
        resolved_days = max(1, min(days, 90))
        end_date = self._parse_iso_date(iso_end_date, "end_date") if iso_end_date else date.today()
        running_fn = getattr(self._dal, "get_recent_running_workouts", None)
        strength_fn = getattr(self._dal, "get_recent_strength_workouts", None)
        running = running_fn(days=resolved_days, end_date=end_date) if callable(running_fn) else []
        strength = strength_fn(days=resolved_days, end_date=end_date) if callable(strength_fn) else []
        return {
            "window": _window_payload(end_date=end_date, days=resolved_days),
            "running": _json_safe(running),
            "strength": _json_safe(strength),
            "data_quality": {
                "running_available": bool(running),
                "strength_available": bool(strength),
            },
        }
        """Perform recent workouts."""

    def coach_state(self, iso_date: str) -> Dict[str, Any]:
        target_date = self._parse_iso_date(iso_date, "date")
        history_start = target_date - timedelta(days=34)
        rows = list(self._dal.get_historical_data(history_start, target_date) or [])
        last_7 = _window_rows(rows, target_date - timedelta(days=6), target_date)
        prev_7 = _window_rows(rows, target_date - timedelta(days=13), target_date - timedelta(days=7))
        last_28 = _window_rows(rows, target_date - timedelta(days=27), target_date)

        weight_7 = _avg(_numeric_values(last_7, "weight_kg"))
        weight_prev_7 = _avg(_numeric_values(prev_7, "weight_kg"))
        weight_rate = None
        if weight_7 is not None and weight_prev_7:
            weight_rate = ((weight_7 - weight_prev_7) / weight_prev_7) * 100.0

        sleep_values = _numeric_values(last_7, "sleep_asleep_minutes") or _numeric_values(last_7, "sleep_total_minutes")
        sleep_debt = sum(max(0.0, 420.0 - value) for value in sleep_values) if sleep_values else None

        rhr_7 = _avg(_numeric_values(last_7, "hr_resting"))
        rhr_28 = _avg(_numeric_values(last_28, "hr_resting"))
        hrv_7 = _avg(_numeric_values(last_7, "hrv_sdnn_ms"))
        hrv_28 = _avg(_numeric_values(last_28, "hrv_sdnn_ms"))
        rhr_delta = rhr_7 - rhr_28 if rhr_7 is not None and rhr_28 is not None else None
        hrv_delta = hrv_7 - hrv_28 if hrv_7 is not None and hrv_28 is not None else None

        workouts = self.recent_workouts(days=14, iso_end_date=target_date.isoformat())
        run_load_7d = self._run_load(workouts.get("running", []), target_date=target_date, days=7)
        strength_load_7d = _sum_field(last_7, "strength_volume_kg")

        plan_context = self.plan_context(target_date.isoformat())
        deload_due = bool(plan_context.get("deload_due"))
        data_quality = self._coach_data_quality(rows=rows, last_7=last_7, target_date=target_date)
        possible_underfueling = self._possible_underfueling(
            weight_rate=weight_rate,
            sleep_debt=sleep_debt,
            rhr_delta=rhr_delta,
            hrv_delta=hrv_delta,
        )
        readiness = self._readiness_state(
            sleep_debt=sleep_debt,
            rhr_delta=rhr_delta,
            hrv_delta=hrv_delta,
            data_quality=data_quality,
            possible_underfueling=possible_underfueling,
        )

        return {
            "date": target_date.isoformat(),
            "summary": {
                "readiness_state": readiness,
                "data_reliability_flag": data_quality["reliability_flag"],
                "possible_underfueling_flag": possible_underfueling,
                "deload_due": deload_due,
            },
            "derived": {
                "weight_rate_pct_bw_per_week": _json_safe(weight_rate),
                "sleep_debt_7d_minutes": _json_safe(sleep_debt),
                "rhr_delta_vs_28d_bpm": _json_safe(rhr_delta),
                "hrv_delta_vs_28d_ms": _json_safe(hrv_delta),
                "run_load_7d_km": _json_safe(run_load_7d),
                "strength_load_7d_kg": _json_safe(strength_load_7d),
            },
            "baselines": {
                "weight_avg_7d_kg": _json_safe(weight_7),
                "weight_avg_prev_7d_kg": _json_safe(weight_prev_7),
                "sleep_avg_7d_minutes": _json_safe(_avg(sleep_values)),
                "rhr_avg_7d_bpm": _json_safe(rhr_7),
                "rhr_avg_28d_bpm": _json_safe(rhr_28),
                "hrv_avg_7d_ms": _json_safe(hrv_7),
                "hrv_avg_28d_ms": _json_safe(hrv_28),
            },
            "recent_workouts": workouts,
            "plan_context": plan_context,
            "goal_state": self.goal_state(),
            "data_quality": data_quality,
            "missing_subjective_inputs": [
                "pain_location_and_severity",
                "soreness_0_10",
                "hunger_0_10",
                "stress_0_10",
                "gi_issues",
                "schedule_changes",
            ],
            "coaching_notes": [
                "Use wearable calories only as a relative trend, not as a direct calorie target.",
                "Treat body composition percentages, body age, VO2max, and sleep stages as secondary context.",
                "Do not progress running intensity when sleep debt and recovery deltas are adverse.",
            ],
        }
        """Perform coach state."""

    def goal_state(self) -> Dict[str, Any]:
        return {
            "running_goal": {
                "target_race": getattr(settings, "RUNNING_TARGET_RACE", None),
                "race_date": _json_safe(getattr(settings, "RUNNING_RACE_DATE", None)),
                "target_time": getattr(settings, "RUNNING_TARGET_TIME", None),
                "weight_loss_target_kg": _json_safe(getattr(settings, "RUNNING_WEIGHT_LOSS_TARGET_KG", None)),
            },
            "body_composition_goal": {
                "goal_weight_kg": _json_safe(getattr(settings, "USER_GOAL_WEIGHT_KG", None)),
            },
            "strength": {
                "training_maxes_kg": _json_safe(self._latest_training_maxes()),
                "training_max_last_measured_at": _json_safe(self._latest_training_max_date()),
            },
            "performance_anchors": {
                "current_half_marathon_marker": "02:15:00",
                "historical_half_marathon_pb": "01:42:30",
                "sub_3_marathon_half_equivalent": "01:26:20",
            },
        }
        """Perform goal state."""

    def user_notes(self, days: int = 14) -> Dict[str, Any]:
        return {
            "window_days": max(1, min(days, 90)),
            "notes": [],
            "data_quality": {
                "status": "not_configured",
                "message": "Subjective notes are not currently persisted by Pete-Eebot.",
            },
        }
        """Perform user notes."""

    def plan_context(self, iso_date: str) -> Dict[str, Any]:
        target_date = self._parse_iso_date(iso_date, "date")
        active_plan_fn = getattr(self._dal, "get_active_plan", None)
        plan = active_plan_fn() if callable(active_plan_fn) else None
        if not plan:
            return {
                "date": target_date.isoformat(),
                "active_plan": None,
                "deload_due": False,
                "data_quality": "missing_plan",
            }

        start = converters.to_date(plan.get("start_date"))
        weeks = int(plan.get("weeks") or 0)
        current_week = ((target_date - start).days // 7) + 1 if start else None
        deload_due = bool(current_week and current_week % 4 == 0)
        return {
            "date": target_date.isoformat(),
            "active_plan": _json_safe(plan),
            "current_week_number": current_week,
            "total_weeks": weeks,
            "mesocycle": "5/3/1 strength plus running redevelopment",
            "strength_phase": "deload" if deload_due else "build",
            "deload_due": deload_due,
            "next_deload_week_number": self._next_deload_week(current_week, weeks),
            "data_quality": "observed",
        }
        """Perform plan context."""

    @staticmethod
    def _source_for_metric(key: str) -> str:
        return _metric_source(key)
        """Perform source for metric."""

    @staticmethod
    def _completeness_pct(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> float:
        if not rows or not fields:
            return 0.0
        observed = 0
        possible = len(rows) * len(fields)
        for row in rows:
            observed += sum(1 for field in fields if row.get(field) is not None)
        return round((observed / possible) * 100.0, 1) if possible else 0.0
        """Perform completeness pct."""

    @staticmethod
    def _run_load(workouts: list[dict[str, Any]], *, target_date: date, days: int) -> float | None:
        start = target_date - timedelta(days=days - 1)
        total = 0.0
        seen = False
        for workout in workouts:
            workout_date = converters.to_date(workout.get("workout_date") or workout.get("start_time"))
            distance = converters.to_float(workout.get("total_distance_km"))
            if workout_date is None or distance is None:
                continue
            if start <= workout_date <= target_date:
                total += distance
                seen = True
        return total if seen else None
        """Perform run load."""

    def _coach_data_quality(
        self,
        *,
        rows: list[dict[str, Any]],
        last_7: list[dict[str, Any]],
        target_date: date,
    ) -> Dict[str, Any]:
        last_dates = [item for item in (converters.to_date(row.get("date")) for row in rows) if item is not None]
        last_sync = max(last_dates) if last_dates else None
        stale_days = (target_date - last_sync).days if last_sync else None
        completeness = self._completeness_pct(last_7, _PRIMARY_FIELDS)
        reliability = "high"
        if stale_days is None or stale_days > 2 or completeness < 50.0:
            reliability = "low"
        elif stale_days > 0 or completeness < 80.0:
            reliability = "moderate"
        return {
            "last_sync_at": last_sync.isoformat() if last_sync else None,
            "stale_days": stale_days,
            "completeness_pct": completeness,
            "reliability_flag": reliability,
            "primary_fields": list(_PRIMARY_FIELDS),
        }
        """Perform coach data quality."""

    @staticmethod
    def _possible_underfueling(
        *,
        weight_rate: float | None,
        sleep_debt: float | None,
        rhr_delta: float | None,
        hrv_delta: float | None,
    ) -> bool:
        rapid_loss = weight_rate is not None and weight_rate <= -1.0
        recovery_worse = (sleep_debt is not None and sleep_debt >= 210) or (
            rhr_delta is not None and rhr_delta >= 4 and hrv_delta is not None and hrv_delta <= -5
        )
        return bool(rapid_loss and recovery_worse)
        """Perform possible underfueling."""

    @staticmethod
    def _readiness_state(
        *,
        sleep_debt: float | None,
        rhr_delta: float | None,
        hrv_delta: float | None,
        data_quality: dict[str, Any],
        possible_underfueling: bool,
    ) -> str:
        if data_quality.get("reliability_flag") == "low":
            return "amber"
        adverse_recovery = (
            sleep_debt is not None
            and sleep_debt >= 210
            and rhr_delta is not None
            and rhr_delta >= 4
            and hrv_delta is not None
            and hrv_delta <= -5
        )
        if possible_underfueling or adverse_recovery:
            return "red"
        if (sleep_debt is not None and sleep_debt >= 120) or (rhr_delta is not None and rhr_delta >= 3):
            return "amber"
        return "green"
        """Perform readiness state."""

    def _latest_training_maxes(self) -> Dict[str, Any]:
        getter = getattr(self._dal, "get_latest_training_maxes", None)
        return getter() if callable(getter) else {}
        """Perform latest training maxes."""

    def _latest_training_max_date(self) -> date | None:
        getter = getattr(self._dal, "get_latest_training_max_date", None)
        return getter() if callable(getter) else None
        """Perform latest training max date."""

    @staticmethod
    def _next_deload_week(current_week: int | None, total_weeks: int) -> int | None:
        if current_week is None or total_weeks <= 0:
            return None
        week = current_week
        while week <= total_weeks:
            if week % 4 == 0:
                return week
            week += 1
        return None
        """Perform next deload week."""


class PlanService(_DateParserMixin):
    """Service for read-only access to stored plan snapshots."""

    def __init__(self, dal: PostgresDal):
        self._read_model = PlanReadModel(dal)
        """Initialize this object."""

    def for_day(self, iso_date: str) -> Dict[str, Any]:
        target_date = self._parse_iso_date(iso_date, "date")
        return self._read_model.plan_for_day(target_date)
        """Perform for day."""

    def for_week(self, iso_start_date: str) -> Dict[str, Any]:
        target_date = self._parse_iso_date(iso_start_date, "start_date")
        return self._read_model.plan_for_week(target_date)
        """Perform for week."""


class StatusService:
    """Service wrapper for status checks to align with API layers."""

    def __init__(self, dal: PostgresDal):
        self._dal = dal
        """Initialize this object."""

    def run_checks(self, timeout: float):  # pragma: no cover - integration exercised elsewhere
        # Deferred import to avoid a circular dependency during module import in tests
        from pete_e.cli.status import run_status_checks

        return run_status_checks(timeout=timeout)
        """Perform run checks."""
