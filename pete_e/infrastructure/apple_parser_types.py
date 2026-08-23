"""Typed records and outcomes for the internal Apple Health parsing pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict


@dataclass(frozen=True)
class DailyMetricPoint:
    """Represent one canonical daily Apple Health metric value."""

    __module__ = "pete_e.infrastructure.apple_parser"

    date: datetime
    device_name: str
    metric_name: str
    unit: str
    value: float


@dataclass(frozen=True)
class DailyHeartRateSummary:
    """Represent one daily minimum, average, and maximum heart-rate summary."""

    __module__ = "pete_e.infrastructure.apple_parser"

    date: datetime
    device_name: str
    hr_min: int
    hr_avg: float
    hr_max: int


@dataclass(frozen=True)
class DailySleepSummary:
    """Represent one nightly Apple Health sleep summary."""

    __module__ = "pete_e.infrastructure.apple_parser"

    date: datetime
    device_name: str
    sleep_start: datetime
    sleep_end: datetime
    in_bed_start: datetime | None
    in_bed_end: datetime | None
    total_sleep_hrs: float
    core_hrs: float
    deep_hrs: float
    rem_hrs: float
    awake_hrs: float


@dataclass(frozen=True)
class WorkoutHeader:
    """Represent the canonical fields for one Apple Health workout."""

    __module__ = "pete_e.infrastructure.apple_parser"

    workout_id: str
    type_name: str
    device_name: str
    start_time: datetime
    end_time: datetime
    duration_sec: float
    location: str | None
    total_distance_km: float | None
    total_active_energy_kj: float | None
    avg_intensity: float | None
    elevation_gain_m: float | None
    environment_temp_degc: float | None
    environment_humidity_percent: float | None


@dataclass(frozen=True)
class WorkoutHRPoint:
    """Represent one workout heart-rate series point."""

    __module__ = "pete_e.infrastructure.apple_parser"

    workout_id: str
    offset_sec: int
    hr_min: int
    hr_avg: float
    hr_max: int


@dataclass(frozen=True)
class WorkoutStepsPoint:
    """Represent one workout step-count series point."""

    __module__ = "pete_e.infrastructure.apple_parser"

    workout_id: str
    offset_sec: int
    steps: float


@dataclass(frozen=True)
class WorkoutEnergyPoint:
    """Represent one workout active-energy series point."""

    __module__ = "pete_e.infrastructure.apple_parser"

    workout_id: str
    offset_sec: int
    energy_kcal: float


@dataclass(frozen=True)
class WorkoutHRRecoveryPoint:
    """Represent one post-workout heart-rate recovery point."""

    __module__ = "pete_e.infrastructure.apple_parser"

    workout_id: str
    offset_sec: int
    hr_min: int
    hr_avg: int
    hr_max: int


class AppleParseResult(TypedDict):
    """Describe the legacy nine-key dictionary returned by the public adapter."""

    daily_metric_points: list[DailyMetricPoint]
    hr_summaries: list[DailyHeartRateSummary]
    sleep_summaries: list[DailySleepSummary]
    workout_headers: list[WorkoutHeader]
    workout_hr: list[WorkoutHRPoint]
    workout_steps: list[WorkoutStepsPoint]
    workout_energy: list[WorkoutEnergyPoint]
    workout_hr_recovery: list[WorkoutHRRecoveryPoint]
    skipped_row_count: int


@dataclass(frozen=True)
class SkippedRows:
    """Count invalid rows by stream while retaining legacy diagnostic order."""

    metric_rows: int = 0
    heart_rate_entries: int = 0
    sleep_entries: int = 0
    workout_headers: int = 0
    workout_heart_rate_points: int = 0
    workout_energy_rows: int = 0
    workout_step_rows: int = 0
    workout_recovery_rows: int = 0

    def __add__(self, other: SkippedRows) -> SkippedRows:
        return SkippedRows(
            metric_rows=self.metric_rows + other.metric_rows,
            heart_rate_entries=self.heart_rate_entries + other.heart_rate_entries,
            sleep_entries=self.sleep_entries + other.sleep_entries,
            workout_headers=self.workout_headers + other.workout_headers,
            workout_heart_rate_points=(
                self.workout_heart_rate_points + other.workout_heart_rate_points
            ),
            workout_energy_rows=(self.workout_energy_rows + other.workout_energy_rows),
            workout_step_rows=self.workout_step_rows + other.workout_step_rows,
            workout_recovery_rows=(
                self.workout_recovery_rows + other.workout_recovery_rows
            ),
        )

    @property
    def total(self) -> int:
        """Return the total number of invalid rows across all streams."""

        return sum(
            (
                self.metric_rows,
                self.heart_rate_entries,
                self.sleep_entries,
                self.workout_headers,
                self.workout_heart_rate_points,
                self.workout_energy_rows,
                self.workout_step_rows,
                self.workout_recovery_rows,
            )
        )

    def warning_sections(self) -> tuple[str, ...]:
        """Render non-zero counters in the legacy warning order."""

        labelled_counts = (
            (self.metric_rows, "metric rows"),
            (self.heart_rate_entries, "heart rate entries"),
            (self.sleep_entries, "sleep entries"),
            (self.workout_headers, "workout headers"),
            (self.workout_heart_rate_points, "workout heart-rate points"),
            (self.workout_energy_rows, "workout energy rows"),
            (self.workout_step_rows, "workout step rows"),
            (self.workout_recovery_rows, "workout recovery rows"),
        )
        return tuple(f"{count} {label}" for count, label in labelled_counts if count)

    def warning_message(self) -> str | None:
        """Return the single legacy warning, or ``None`` when nothing was skipped."""

        sections = self.warning_sections()
        if not sections:
            return None
        return (
            "Apple Health parser skipped "
            + ", ".join(sections)
            + " due to invalid data."
        )


@dataclass(frozen=True)
class MetricMapping:
    """Hold the typed output from recognising and mapping one metric record."""

    daily_metric_points: tuple[DailyMetricPoint, ...] = ()
    heart_rate_summaries: tuple[DailyHeartRateSummary, ...] = ()
    sleep_summaries: tuple[DailySleepSummary, ...] = ()
    skipped_rows: SkippedRows = SkippedRows()


@dataclass(frozen=True)
class WorkoutMapping:
    """Hold the typed output from recognising and mapping one workout record."""

    headers: tuple[WorkoutHeader, ...] = ()
    heart_rate_points: tuple[WorkoutHRPoint, ...] = ()
    step_points: tuple[WorkoutStepsPoint, ...] = ()
    energy_points: tuple[WorkoutEnergyPoint, ...] = ()
    recovery_points: tuple[WorkoutHRRecoveryPoint, ...] = ()
    skipped_rows: SkippedRows = SkippedRows()


@dataclass(frozen=True)
class AppleParseOutcome:
    """Represent all mapped streams plus centralised parser diagnostics."""

    daily_metric_points: tuple[DailyMetricPoint, ...]
    heart_rate_summaries: tuple[DailyHeartRateSummary, ...]
    sleep_summaries: tuple[DailySleepSummary, ...]
    workout_headers: tuple[WorkoutHeader, ...]
    workout_heart_rate: tuple[WorkoutHRPoint, ...]
    workout_steps: tuple[WorkoutStepsPoint, ...]
    workout_energy: tuple[WorkoutEnergyPoint, ...]
    workout_recovery: tuple[WorkoutHRRecoveryPoint, ...]
    skipped_rows: SkippedRows

    def as_legacy_result(self) -> AppleParseResult:
        """Assemble the stable list-valued dictionary returned by the adapter."""

        return {
            "daily_metric_points": list(self.daily_metric_points),
            "hr_summaries": list(self.heart_rate_summaries),
            "sleep_summaries": list(self.sleep_summaries),
            "workout_headers": list(self.workout_headers),
            "workout_hr": list(self.workout_heart_rate),
            "workout_steps": list(self.workout_steps),
            "workout_energy": list(self.workout_energy),
            "workout_hr_recovery": list(self.workout_recovery),
            "skipped_row_count": self.skipped_rows.total,
        }
