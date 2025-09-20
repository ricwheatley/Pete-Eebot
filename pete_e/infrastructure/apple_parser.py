# pete_e/infrastructure/apple_parser.py
# British English comments and docstrings.

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

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
        data = root.get("data", {})
        metrics = data.get("metrics", [])
        workouts = data.get("workouts", [])

        daily_metric_points: List[DailyMetricPoint] = []
        hr_summaries: List[DailyHeartRateSummary] = []
        sleep_summaries: List[DailySleepSummary] = []
        workout_headers: List[WorkoutHeader] = []
        workout_hr: List[WorkoutHRPoint] = []
        workout_steps: List[WorkoutStepsPoint] = []
        workout_energy: List[WorkoutEnergyPoint] = []
        workout_hr_recovery: List[WorkoutHRRecoveryPoint] = []

        # --- Metrics ---
        for m in metrics:
            name = str(m.get("name") or "").strip()
            unit = str(m.get("units") or "").strip()
            if not name or name in SKIP_METRICS:
                continue

            if name == "heart_rate":
                for row in m.get("data", []):
                    date = self._parse_dt(row.get("date"))
                    if not date: continue
                    device = str(row.get("source", "Unknown")).strip()
                    hr_min = int(round(float(row.get("Min", 0.0))))
                    hr_avg = float(row.get("Avg", 0.0))
                    hr_max = int(round(float(row.get("Max", 0.0))))
                    hr_summaries.append(
                        DailyHeartRateSummary(date=date, device_name=device, hr_min=hr_min, hr_avg=hr_avg, hr_max=hr_max)
                    )
                continue

            if name == "sleep_analysis":
                for row in m.get("data", []):
                    date = self._parse_dt(row.get("date"))
                    sleep_start = self._parse_dt(row.get("sleepStart"))
                    sleep_end = self._parse_dt(row.get("sleepEnd"))
                    if not date or not sleep_start or not sleep_end: continue

                    device = str(row.get("source", "Unknown")).strip()
                    in_bed_start = self._parse_dt(row.get("inBedStart"))
                    in_bed_end = self._parse_dt(row.get("inBedEnd"))
                    
                    sleep_summaries.append(
                        DailySleepSummary(
                            date=date, device_name=device, sleep_start=sleep_start, sleep_end=sleep_end,
                            in_bed_start=in_bed_start, in_bed_end=in_bed_end,
                            total_sleep_hrs=float(row.get("totalSleep", 0.0)), core_hrs=float(row.get("core", 0.0)),
                            deep_hrs=float(row.get("deep", 0.0)), rem_hrs=float(row.get("rem", 0.0)),
                            awake_hrs=float(row.get("awake", 0.0)),
                        )
                    )
                continue

            canonical = self._canon_metric_name(name)
            for row in m.get("data", []):
                date = self._parse_dt(row.get("date"))
                if not date: continue
                device = str(row.get("source", "Unknown")).strip()
                qty = float(row.get("qty", 0.0))
                daily_metric_points.append(
                    DailyMetricPoint(date=date, device_name=device, metric_name=canonical, unit=unit, value=qty)
                )

        # --- Workouts ---
        for w in workouts:
            workout_id = str(w.get("id", "")).strip()
            start = self._parse_dt(w.get("start"))
            end = self._parse_dt(w.get("end"))
            if not workout_id or not start or not end: continue
            
            type_name = str(w.get("name", "Other")).strip()
            duration = float(w.get("duration", 0.0))
            location = w.get("location") and str(w.get("location"))

            device_name = "Unknown Device"
            for series_key in ("heartRateData", "activeEnergy", "stepCount"):
                if series := w.get(series_key):
                    if series:
                        device_name = str(series[0].get("source", device_name)).strip()
                        break

            header = WorkoutHeader(
                workout_id=workout_id, type_name=type_name, device_name=device_name,
                start_time=start, end_time=end, duration_sec=duration, location=location,
                total_distance_km=self._get_numeric_value(w.get("distance") or w.get("walkingRunningDistance")),
                total_active_energy_kj=self._get_numeric_value(w.get("activeEnergyBurned")),
                avg_intensity=self._get_numeric_value(w.get("intensity")),
                elevation_gain_m=self._get_numeric_value(w.get("elevationUp")),
                environment_temp_degc=self._get_numeric_value(w.get("temperature")),
                environment_humidity_percent=self._get_numeric_value(w.get("humidity")),
            )
            workout_headers.append(header)

            # [CHANGED] Per-minute HR with clamping logic
            for row in w.get("heartRateData", []):
                t = self._parse_dt(row.get("date"))
                if not t: continue
                offset = int((t - start).total_seconds())
                
                hr_min = int(round(float(row.get("Min", 0.0))))
                hr_avg = float(row.get("Avg", 0.0))
                hr_max = int(round(float(row.get("Max", 0.0))))
                
                # Clamp the average to handle rounding discrepancies from the source data.
                clamped_avg = max(hr_min, min(hr_avg, hr_max))
                
                workout_hr.append(
                    WorkoutHRPoint(
                        workout_id=workout_id, offset_sec=max(0, offset),
                        hr_min=hr_min, hr_avg=clamped_avg, hr_max=hr_max,
                    )
                )

            # Per-minute energy (kcal)
            for row in w.get("activeEnergy", []):
                t = self._parse_dt(row.get("date"))
                if not t: continue
                offset = int((t - start).total_seconds())
                workout_energy.append(
                    WorkoutEnergyPoint(
                        workout_id=workout_id, offset_sec=max(0, offset),
                        energy_kcal=float(row.get("qty", 0.0)),
                    )
                )
            
            # Per-minute steps
            for row in w.get("stepCount", []):
                t = self._parse_dt(row.get("date"))
                if not t: continue
                offset = int((t - start).total_seconds())
                workout_steps.append(
                    WorkoutStepsPoint(
                        workout_id=workout_id, offset_sec=max(0, offset),
                        steps=float(row.get("qty", 0.0)),
                    )
                )

            # [CHANGED] HR Recovery with clamping logic
            for row in w.get("heartRateRecovery", []):
                t = self._parse_dt(row.get("date"))
                if not t: continue
                offset = int((t - end).total_seconds())
                
                hr_min = int(round(float(row.get("Min", 0.0))))
                hr_avg_raw = float(row.get("Avg", 0.0))
                hr_max = int(round(float(row.get("Max", 0.0))))
                
                # Clamp the average to handle rounding discrepancies.
                clamped_avg = int(round(max(hr_min, min(hr_avg_raw, hr_max))))
                
                workout_hr_recovery.append(
                    WorkoutHRRecoveryPoint(
                        workout_id=workout_id, offset_sec=max(0, offset),
                        hr_min=hr_min, hr_avg=clamped_avg, hr_max=hr_max,
                    )
                )

        return {
            "daily_metric_points": daily_metric_points, "hr_summaries": hr_summaries,
            "sleep_summaries": sleep_summaries, "workout_headers": workout_headers,
            "workout_hr": workout_hr, "workout_steps": workout_steps,
            "workout_energy": workout_energy, "workout_hr_recovery": workout_hr_recovery,
        }