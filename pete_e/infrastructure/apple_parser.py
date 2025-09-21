# pete_e/infrastructure/apple_parser.py
# British English comments and docstrings.

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from pete_e.infrastructure import log_utils

ISO_WITH_TZ = "%Y-%m-%d %H:%M:%S %z"

CANONICAL_METRIC_NAME = {
    "walking_running_distance": "distance_walking_running",
}
SKIP_METRICS = {
    "weight_body_mass",
    "body_fat_percentage",
    "body_mass_index",
    "lean_body_mass",
}

@dataclass(frozen=True)
class DailyMetricPoint:
    date: datetime
    device_name: str
    metric_name: str
    unit: str
    value: float

@dataclass(frozen=True)
class DailyHeartRateSummary:
    date: datetime
    device_name: str
    hr_min: int
    hr_avg: float
    hr_max: int

@dataclass(frozen=True)
class DailySleepSummary:
    date: datetime
    device_name: str
    sleep_start: datetime
    sleep_end: datetime
    in_bed_start: Optional[datetime]
    in_bed_end: Optional[datetime]
    total_sleep_hrs: float
    core_hrs: float
    deep_hrs: float
    rem_hrs: float
    awake_hrs: float

@dataclass(frozen=True)
class WorkoutHeader:
    workout_id: str
    type_name: str
    device_name: str
    start_time: datetime
    end_time: datetime
    duration_sec: float
    location: Optional[str]
    total_distance_km: Optional[float]
    total_active_energy_kj: Optional[float]
    avg_intensity: Optional[float]
    elevation_gain_m: Optional[float]
    environment_temp_degc: Optional[float]
    environment_humidity_percent: Optional[float]

@dataclass(frozen=True)
class WorkoutHRPoint:
    workout_id: str
    offset_sec: int
    hr_min: int
    hr_avg: float
    hr_max: int

@dataclass(frozen=True)
class WorkoutStepsPoint:
    workout_id: str
    offset_sec: int
    steps: float

@dataclass(frozen=True)
class WorkoutEnergyPoint:
    workout_id: str
    offset_sec: int
    energy_kcal: float

@dataclass(frozen=True)
class WorkoutHRRecoveryPoint:
    workout_id: str
    offset_sec: int
    hr_min: int
    hr_avg: int
    hr_max: int


class AppleHealthParser:
    """Parse a HealthAutoExport JSON document into domain rows for persistence."""

    @staticmethod
    def _parse_dt(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        return datetime.strptime(value, ISO_WITH_TZ)

    @staticmethod
    def _canon_metric_name(name: str) -> str:
        return CANONICAL_METRIC_NAME.get(name, name)

    @staticmethod
    def _get_numeric_value(data) -> Optional[float]:
        """Safely extracts a float from a number, string, or a {'qty': x} dict."""
        if data is None:
            return None
        if isinstance(data, (int, float)):
            return float(data)
        if isinstance(data, dict):
            data = data.get("qty")
        
        if data is not None:
            try:
                return float(data)
            except (ValueError, TypeError):
                return None
        return None

    def parse(self, root: dict) -> Dict[str, Iterable]:
        """Parse root HealthAutoExport JSON into typed streams for persistence."""
        data = root.get("data") if isinstance(root, dict) else {}
        if not isinstance(data, dict):
            data = {}

        metrics = data.get("metrics") if data else []
        if not isinstance(metrics, list):
            metrics = []

        workouts = data.get("workouts") if data else []
        if not isinstance(workouts, list):
            workouts = []

        daily_metric_points: List[DailyMetricPoint] = []
        hr_summaries: List[DailyHeartRateSummary] = []
        sleep_summaries: List[DailySleepSummary] = []
        workout_headers: List[WorkoutHeader] = []
        workout_hr: List[WorkoutHRPoint] = []
        workout_steps: List[WorkoutStepsPoint] = []
        workout_energy: List[WorkoutEnergyPoint] = []
        workout_hr_recovery: List[WorkoutHRRecoveryPoint] = []

        skipped_metric_rows = 0
        skipped_hr_rows = 0
        skipped_sleep_rows = 0
        skipped_workout_headers = 0
        skipped_workout_hr_rows = 0
        skipped_workout_energy_rows = 0
        skipped_workout_steps_rows = 0
        skipped_workout_recovery_rows = 0
        # --- Metrics ---
        for m in metrics:
            if not isinstance(m, dict):
                skipped_metric_rows += 1
                continue

            name = str(m.get("name") or "").strip()
            unit = str(m.get("units") or "").strip()
            if not name or name in SKIP_METRICS:
                continue

            rows_value = m.get("data")
            rows = rows_value if isinstance(rows_value, list) else m.get("data", [])
            if not isinstance(rows, list):
                if name == "heart_rate":
                    skipped_hr_rows += 1
                elif name == "sleep_analysis":
                    skipped_sleep_rows += 1
                else:
                    skipped_metric_rows += 1
                continue

            if name == "heart_rate":
                for row in rows:
                    if not isinstance(row, dict):
                        skipped_hr_rows += 1
                        continue
                    date = self._parse_dt(row.get("date"))
                    if not date:
                        skipped_hr_rows += 1
                        continue
                    device = str(row.get("source", "Unknown")).strip()

                    hr_min_val = self._get_numeric_value(row.get("Min"))
                    hr_avg_val = self._get_numeric_value(row.get("Avg"))
                    hr_max_val = self._get_numeric_value(row.get("Max"))
                    if any(value is None for value in (hr_min_val, hr_avg_val, hr_max_val)):
                        skipped_hr_rows += 1
                        continue

                    hr_min = int(round(hr_min_val))
                    hr_max = int(round(hr_max_val))
                    hr_avg = max(hr_min, min(hr_avg_val, hr_max))

                    hr_summaries.append(
                        DailyHeartRateSummary(
                            date=date,
                            device_name=device,
                            hr_min=hr_min,
                            hr_avg=hr_avg,
                            hr_max=hr_max,
                        )
                    )
                continue

            if name == "sleep_analysis":
                for row in rows:
                    if not isinstance(row, dict):
                        skipped_sleep_rows += 1
                        continue
                    date = self._parse_dt(row.get("date"))
                    sleep_start = self._parse_dt(row.get("sleepStart"))
                    sleep_end = self._parse_dt(row.get("sleepEnd"))
                    if not date or not sleep_start or not sleep_end:
                        skipped_sleep_rows += 1
                        continue

                    device = str(row.get("source", "Unknown")).strip()
                    in_bed_start = self._parse_dt(row.get("inBedStart"))
                    in_bed_end = self._parse_dt(row.get("inBedEnd"))

                    total_sleep = self._get_numeric_value(row.get("totalSleep")) or 0.0
                    core = self._get_numeric_value(row.get("core")) or 0.0
                    deep = self._get_numeric_value(row.get("deep")) or 0.0
                    rem = self._get_numeric_value(row.get("rem")) or 0.0
                    awake = self._get_numeric_value(row.get("awake")) or 0.0

                    sleep_summaries.append(
                        DailySleepSummary(
                            date=date,
                            device_name=device,
                            sleep_start=sleep_start,
                            sleep_end=sleep_end,
                            in_bed_start=in_bed_start,
                            in_bed_end=in_bed_end,
                            total_sleep_hrs=total_sleep,
                            core_hrs=core,
                            deep_hrs=deep,
                            rem_hrs=rem,
                            awake_hrs=awake,
                        )
                    )
                continue

            canonical = self._canon_metric_name(name)
            for row in rows:
                if not isinstance(row, dict):
                    skipped_metric_rows += 1
                    continue
                date = self._parse_dt(row.get("date"))
                if not date:
                    skipped_metric_rows += 1
                    continue
                device = str(row.get("source", "Unknown")).strip()
                qty = self._get_numeric_value(row.get("qty"))
                if qty is None:
                    skipped_metric_rows += 1
                    continue

                daily_metric_points.append(
                    DailyMetricPoint(
                        date=date,
                        device_name=device,
                        metric_name=canonical,
                        unit=unit,
                        value=qty,
                    )
                )
        # --- Workouts ---
        for w in workouts:
            if not isinstance(w, dict):
                skipped_workout_headers += 1
                continue

            workout_id = str(w.get("id", "")).strip()
            start = self._parse_dt(w.get("start"))
            end = self._parse_dt(w.get("end"))
            if not workout_id or not start or not end:
                skipped_workout_headers += 1
                continue

            type_name = str(w.get("name", "Other")).strip() or "Other"
            duration = self._get_numeric_value(w.get("duration")) or 0.0
            location = w.get("location")
            if location not in (None, ""):
                location = str(location)
            else:
                location = None

            device_name = "Unknown Device"
            for series_key in ("heartRateData", "activeEnergy", "stepCount"):
                series = w.get(series_key)
                if isinstance(series, list) and series:
                    first = series[0]
                    if isinstance(first, dict):
                        candidate = str(first.get("source", device_name)).strip()
                        if candidate:
                            device_name = candidate
                        break

            header = WorkoutHeader(
                workout_id=workout_id,
                type_name=type_name,
                device_name=device_name,
                start_time=start,
                end_time=end,
                duration_sec=duration,
                location=location,
                total_distance_km=self._get_numeric_value(w.get("distance") or w.get("walkingRunningDistance")),
                total_active_energy_kj=self._get_numeric_value(w.get("activeEnergyBurned")),
                avg_intensity=self._get_numeric_value(w.get("intensity")),
                elevation_gain_m=self._get_numeric_value(w.get("elevationUp")),
                environment_temp_degc=self._get_numeric_value(w.get("temperature")),
                environment_humidity_percent=self._get_numeric_value(w.get("humidity")),
            )
            workout_headers.append(header)

            heart_rate_rows = w.get("heartRateData", [])
            if not isinstance(heart_rate_rows, list):
                skipped_workout_hr_rows += 1
            else:
                for row in heart_rate_rows:
                    if not isinstance(row, dict):
                        skipped_workout_hr_rows += 1
                        continue
                    t = self._parse_dt(row.get("date"))
                    if not t:
                        skipped_workout_hr_rows += 1
                        continue
                    offset = int(max(0.0, (t - start).total_seconds()))

                    hr_min_val = self._get_numeric_value(row.get("Min"))
                    hr_avg_val = self._get_numeric_value(row.get("Avg"))
                    hr_max_val = self._get_numeric_value(row.get("Max"))
                    if any(value is None for value in (hr_min_val, hr_avg_val, hr_max_val)):
                        skipped_workout_hr_rows += 1
                        continue

                    hr_min = int(round(hr_min_val))
                    hr_max = int(round(hr_max_val))
                    hr_avg = max(hr_min, min(hr_avg_val, hr_max))

                    workout_hr.append(
                        WorkoutHRPoint(
                            workout_id=workout_id,
                            offset_sec=offset,
                            hr_min=hr_min,
                            hr_avg=hr_avg,
                            hr_max=hr_max,
                        )
                    )

            energy_rows = w.get("activeEnergy", [])
            if not isinstance(energy_rows, list):
                skipped_workout_energy_rows += 1
            else:
                for row in energy_rows:
                    if not isinstance(row, dict):
                        skipped_workout_energy_rows += 1
                        continue
                    t = self._parse_dt(row.get("date"))
                    if not t:
                        skipped_workout_energy_rows += 1
                        continue
                    offset = int(max(0.0, (t - start).total_seconds()))
                    energy_qty = self._get_numeric_value(row.get("qty"))
                    if energy_qty is None:
                        skipped_workout_energy_rows += 1
                        continue

                    workout_energy.append(
                        WorkoutEnergyPoint(
                            workout_id=workout_id,
                            offset_sec=offset,
                            energy_kcal=energy_qty,
                        )
                    )

            step_rows = w.get("stepCount", [])
            if not isinstance(step_rows, list):
                skipped_workout_steps_rows += 1
            else:
                for row in step_rows:
                    if not isinstance(row, dict):
                        skipped_workout_steps_rows += 1
                        continue
                    t = self._parse_dt(row.get("date"))
                    if not t:
                        skipped_workout_steps_rows += 1
                        continue
                    offset = int(max(0.0, (t - start).total_seconds()))
                    steps_qty = self._get_numeric_value(row.get("qty"))
                    if steps_qty is None:
                        skipped_workout_steps_rows += 1
                        continue

                    workout_steps.append(
                        WorkoutStepsPoint(
                            workout_id=workout_id,
                            offset_sec=offset,
                            steps=steps_qty,
                        )
                    )

            recovery_rows = w.get("heartRateRecovery", [])
            if not isinstance(recovery_rows, list):
                skipped_workout_recovery_rows += 1
            else:
                for row in recovery_rows:
                    if not isinstance(row, dict):
                        skipped_workout_recovery_rows += 1
                        continue
                    t = self._parse_dt(row.get("date"))
                    if not t:
                        skipped_workout_recovery_rows += 1
                        continue
                    offset = int(max(0.0, (t - end).total_seconds()))

                    hr_min_val = self._get_numeric_value(row.get("Min"))
                    hr_avg_val = self._get_numeric_value(row.get("Avg"))
                    hr_max_val = self._get_numeric_value(row.get("Max"))
                    if any(value is None for value in (hr_min_val, hr_avg_val, hr_max_val)):
                        skipped_workout_recovery_rows += 1
                        continue

                    hr_min = int(round(hr_min_val))
                    hr_max = int(round(hr_max_val))
                    hr_avg = int(round(max(hr_min, min(hr_avg_val, hr_max))))

                    workout_hr_recovery.append(
                        WorkoutHRRecoveryPoint(
                            workout_id=workout_id,
                            offset_sec=offset,
                            hr_min=hr_min,
                            hr_avg=hr_avg,
                            hr_max=hr_max,
                        )
                    )
        skipped_sections: List[str] = []
        if skipped_metric_rows:
            skipped_sections.append(f"{skipped_metric_rows} metric rows")
        if skipped_hr_rows:
            skipped_sections.append(f"{skipped_hr_rows} heart rate entries")
        if skipped_sleep_rows:
            skipped_sections.append(f"{skipped_sleep_rows} sleep entries")
        if skipped_workout_headers:
            skipped_sections.append(f"{skipped_workout_headers} workout headers")
        if skipped_workout_hr_rows:
            skipped_sections.append(f"{skipped_workout_hr_rows} workout heart-rate points")
        if skipped_workout_energy_rows:
            skipped_sections.append(f"{skipped_workout_energy_rows} workout energy rows")
        if skipped_workout_steps_rows:
            skipped_sections.append(f"{skipped_workout_steps_rows} workout step rows")
        if skipped_workout_recovery_rows:
            skipped_sections.append(f"{skipped_workout_recovery_rows} workout recovery rows")

        if skipped_sections:
            log_utils.log_message(
                "Apple Health parser skipped " + ", ".join(skipped_sections) + " due to invalid data.",
                "WARN",
            )
        return {
            "daily_metric_points": daily_metric_points, "hr_summaries": hr_summaries,
            "sleep_summaries": sleep_summaries, "workout_headers": workout_headers,
            "workout_hr": workout_hr, "workout_steps": workout_steps,
            "workout_energy": workout_energy, "workout_hr_recovery": workout_hr_recovery,
        }