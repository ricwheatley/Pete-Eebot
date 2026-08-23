"""Typed recognition and stream-mapping stages for Apple Health JSON records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Final

from pete_e.infrastructure.apple_parser_normalization import (
    RawDict,
    as_raw_dict,
    as_raw_list,
    normalise_heart_rate,
    normalise_workout_environment,
    numeric_value,
    parse_datetime,
)
from pete_e.infrastructure.apple_parser_types import (
    AppleParseOutcome,
    DailyHeartRateSummary,
    DailyMetricPoint,
    DailySleepSummary,
    MetricMapping,
    SkippedRows,
    WorkoutEnergyPoint,
    WorkoutHeader,
    WorkoutHRPoint,
    WorkoutHRRecoveryPoint,
    WorkoutMapping,
    WorkoutStepsPoint,
)


CANONICAL_METRIC_NAME: Final = MappingProxyType(
    {
        "walking_running_distance": "distance_walking_running",
        "heart_rate_variability": "hrv_sdnn_ms",
        "heart_rate_variability_sdnn": "hrv_sdnn_ms",
        "heart_rate_variability_sdnn_ms": "hrv_sdnn_ms",
        "hrv_sdnn": "hrv_sdnn_ms",
        "hrv_sdnn_ms": "hrv_sdnn_ms",
        "vo2max": "vo2_max",
        "vo2_max": "vo2_max",
        "vo2_ml_kg_min": "vo2_max",
        "cardio_vo2_max": "vo2_max",
    }
)
SKIP_METRICS: Final = frozenset(
    {
        "weight_body_mass",
        "body_fat_percentage",
        "body_mass_index",
        "lean_body_mass",
    }
)


@dataclass(frozen=True)
class RecognisedRoot:
    """Hold the two supported top-level record containers in input order."""

    metrics: tuple[object, ...]
    workouts: tuple[object, ...]


@dataclass(frozen=True)
class WorkoutContext:
    """Hold a mapped header plus timestamps needed by its series stages."""

    header: WorkoutHeader
    start: datetime
    end: datetime


def recognise_root(root: object) -> RecognisedRoot:
    """Recognise supported root containers while tolerating legacy wrong shapes."""

    root_mapping = as_raw_dict(root)
    if root_mapping is None:
        return RecognisedRoot((), ())
    data = as_raw_dict(root_mapping.get("data"))
    if data is None:
        return RecognisedRoot((), ())
    metrics = as_raw_list(data.get("metrics"))
    workouts = as_raw_list(data.get("workouts"))
    return RecognisedRoot(
        tuple(metrics) if metrics is not None else (),
        tuple(workouts) if workouts is not None else (),
    )


def canonical_metric_name(name: str) -> str:
    """Return the persisted canonical name for a supported Apple alias."""

    return CANONICAL_METRIC_NAME.get(name, name)


def map_metric_record(raw_metric: object) -> MetricMapping:
    """Recognise and map one top-level metric object into its typed stream."""

    metric = as_raw_dict(raw_metric)
    if metric is None:
        return MetricMapping(skipped_rows=SkippedRows(metric_rows=1))
    name = str(metric.get("name") or "").strip()
    unit = str(metric.get("units") or "").strip()
    if not name or name in SKIP_METRICS:
        return MetricMapping()
    rows = _recognise_series(metric, "data")
    if rows is None:
        return _invalid_metric_container(name)
    if name == "heart_rate":
        return _map_daily_heart_rate(rows)
    if name == "sleep_analysis":
        return _map_daily_sleep(rows)
    return _map_daily_metric(rows, canonical_metric_name(name), unit)


def _invalid_metric_container(name: str) -> MetricMapping:
    if name == "heart_rate":
        return MetricMapping(skipped_rows=SkippedRows(heart_rate_entries=1))
    if name == "sleep_analysis":
        return MetricMapping(skipped_rows=SkippedRows(sleep_entries=1))
    return MetricMapping(skipped_rows=SkippedRows(metric_rows=1))


def _recognise_series(
    container: RawDict,
    key: str,
) -> tuple[object, ...] | None:
    if key not in container:
        return ()
    rows = as_raw_list(container.get(key))
    if rows is None:
        return None
    return tuple(rows)


def _map_daily_heart_rate(rows: tuple[object, ...]) -> MetricMapping:
    summaries: list[DailyHeartRateSummary] = []
    skipped = 0
    for raw_row in rows:
        summary = map_daily_heart_rate_row(raw_row)
        if summary is None:
            skipped += 1
        else:
            summaries.append(summary)
    return MetricMapping(
        heart_rate_summaries=tuple(summaries),
        skipped_rows=SkippedRows(heart_rate_entries=skipped),
    )


def map_daily_heart_rate_row(raw_row: object) -> DailyHeartRateSummary | None:
    """Map one daily heart-rate row, returning ``None`` for a skippable row."""

    row = as_raw_dict(raw_row)
    if row is None:
        return None
    date = parse_datetime(row.get("date"))
    if not date:
        return None
    heart_rate = normalise_heart_rate(row.get("Min"), row.get("Avg"), row.get("Max"))
    if heart_rate is None:
        return None
    return DailyHeartRateSummary(
        date=date,
        device_name=str(row.get("source", "Unknown")).strip(),
        hr_min=heart_rate.minimum,
        hr_avg=heart_rate.average,
        hr_max=heart_rate.maximum,
    )


def _map_daily_sleep(rows: tuple[object, ...]) -> MetricMapping:
    summaries: list[DailySleepSummary] = []
    skipped = 0
    for raw_row in rows:
        summary = map_daily_sleep_row(raw_row)
        if summary is None:
            skipped += 1
        else:
            summaries.append(summary)
    return MetricMapping(
        sleep_summaries=tuple(summaries),
        skipped_rows=SkippedRows(sleep_entries=skipped),
    )


def map_daily_sleep_row(raw_row: object) -> DailySleepSummary | None:
    """Map one daily sleep row, retaining existing defaults and errors."""

    row = as_raw_dict(raw_row)
    if row is None:
        return None
    date = parse_datetime(row.get("date"))
    sleep_start = parse_datetime(row.get("sleepStart"))
    sleep_end = parse_datetime(row.get("sleepEnd"))
    if not date or not sleep_start or not sleep_end:
        return None
    return DailySleepSummary(
        date=date,
        device_name=str(row.get("source", "Unknown")).strip(),
        sleep_start=sleep_start,
        sleep_end=sleep_end,
        in_bed_start=parse_datetime(row.get("inBedStart")),
        in_bed_end=parse_datetime(row.get("inBedEnd")),
        total_sleep_hrs=numeric_value(row.get("totalSleep")) or 0.0,
        core_hrs=numeric_value(row.get("core")) or 0.0,
        deep_hrs=numeric_value(row.get("deep")) or 0.0,
        rem_hrs=numeric_value(row.get("rem")) or 0.0,
        awake_hrs=numeric_value(row.get("awake")) or 0.0,
    )


def _map_daily_metric(
    rows: tuple[object, ...],
    canonical_name: str,
    unit: str,
) -> MetricMapping:
    points: list[DailyMetricPoint] = []
    skipped = 0
    for raw_row in rows:
        point = map_daily_metric_row(raw_row, canonical_name, unit)
        if point is None:
            skipped += 1
        else:
            points.append(point)
    return MetricMapping(
        daily_metric_points=tuple(points),
        skipped_rows=SkippedRows(metric_rows=skipped),
    )


def map_daily_metric_row(
    raw_row: object,
    canonical_name: str,
    unit: str,
) -> DailyMetricPoint | None:
    """Map one ordinary daily metric row into its canonical output record."""

    row = as_raw_dict(raw_row)
    if row is None:
        return None
    date = parse_datetime(row.get("date"))
    if not date:
        return None
    quantity = numeric_value(row.get("qty"))
    if quantity is None:
        return None
    return DailyMetricPoint(
        date=date,
        device_name=str(row.get("source", "Unknown")).strip(),
        metric_name=canonical_name,
        unit=unit,
        value=quantity,
    )


def map_workout_record(raw_workout: object) -> WorkoutMapping:
    """Recognise and map one workout header followed by all supported series."""

    workout = as_raw_dict(raw_workout)
    if workout is None:
        return WorkoutMapping(skipped_rows=SkippedRows(workout_headers=1))
    context = map_workout_header(workout)
    if context is None:
        return WorkoutMapping(skipped_rows=SkippedRows(workout_headers=1))
    heart_rate, skipped_heart_rate = _map_workout_heart_rate(workout, context)
    energy, skipped_energy = _map_workout_energy(workout, context)
    steps, skipped_steps = _map_workout_steps(workout, context)
    recovery, skipped_recovery = _map_workout_recovery(workout, context)
    return WorkoutMapping(
        headers=(context.header,),
        heart_rate_points=heart_rate,
        step_points=steps,
        energy_points=energy,
        recovery_points=recovery,
        skipped_rows=SkippedRows(
            workout_heart_rate_points=skipped_heart_rate,
            workout_energy_rows=skipped_energy,
            workout_step_rows=skipped_steps,
            workout_recovery_rows=skipped_recovery,
        ),
    )


def map_workout_header(workout: RawDict) -> WorkoutContext | None:
    """Map a valid workout header and retain its series timestamp context."""

    workout_id = str(workout.get("id", "")).strip()
    start = parse_datetime(workout.get("start"))
    end = parse_datetime(workout.get("end"))
    if not workout_id or not start or not end:
        return None
    environment = normalise_workout_environment(workout)
    header = WorkoutHeader(
        workout_id=workout_id,
        type_name=str(workout.get("name", "Other")).strip() or "Other",
        device_name=select_workout_device(workout),
        start_time=start,
        end_time=end,
        duration_sec=numeric_value(workout.get("duration")) or 0.0,
        location=_workout_location(workout.get("location")),
        total_distance_km=numeric_value(
            workout.get("distance") or workout.get("walkingRunningDistance")
        ),
        total_active_energy_kj=numeric_value(workout.get("activeEnergyBurned")),
        avg_intensity=numeric_value(workout.get("intensity")),
        elevation_gain_m=numeric_value(workout.get("elevationUp")),
        environment_temp_degc=environment.temperature_degc,
        environment_humidity_percent=environment.humidity_percent,
    )
    return WorkoutContext(header, start, end)


def _workout_location(raw_location: object) -> str | None:
    if raw_location in (None, ""):
        return None
    return str(raw_location)


def select_workout_device(workout: RawDict) -> str:
    """Select a source using the legacy series and first-row preference."""

    device_name = "Unknown Device"
    for series_key in ("heartRateData", "activeEnergy", "stepCount"):
        series = as_raw_list(workout.get(series_key))
        if series:
            first = as_raw_dict(series[0])
            if first is not None:
                candidate = str(first.get("source", device_name)).strip()
                if candidate:
                    device_name = candidate
                break
    return device_name


def _map_workout_heart_rate(
    workout: RawDict,
    context: WorkoutContext,
) -> tuple[tuple[WorkoutHRPoint, ...], int]:
    rows = _recognise_series(workout, "heartRateData")
    if rows is None:
        return (), 1
    points: list[WorkoutHRPoint] = []
    skipped = 0
    for raw_row in rows:
        point = map_workout_heart_rate_row(raw_row, context)
        if point is None:
            skipped += 1
        else:
            points.append(point)
    return tuple(points), skipped


def map_workout_heart_rate_row(
    raw_row: object,
    context: WorkoutContext,
) -> WorkoutHRPoint | None:
    """Map one workout heart-rate point relative to workout start."""

    row = as_raw_dict(raw_row)
    if row is None:
        return None
    timestamp = parse_datetime(row.get("date"))
    if not timestamp:
        return None
    heart_rate = normalise_heart_rate(row.get("Min"), row.get("Avg"), row.get("Max"))
    if heart_rate is None:
        return None
    return WorkoutHRPoint(
        workout_id=context.header.workout_id,
        offset_sec=_offset_seconds(timestamp, context.start),
        hr_min=heart_rate.minimum,
        hr_avg=heart_rate.average,
        hr_max=heart_rate.maximum,
    )


def _map_workout_energy(
    workout: RawDict,
    context: WorkoutContext,
) -> tuple[tuple[WorkoutEnergyPoint, ...], int]:
    rows = _recognise_series(workout, "activeEnergy")
    if rows is None:
        return (), 1
    points: list[WorkoutEnergyPoint] = []
    skipped = 0
    for raw_row in rows:
        point = map_workout_energy_row(raw_row, context)
        if point is None:
            skipped += 1
        else:
            points.append(point)
    return tuple(points), skipped


def map_workout_energy_row(
    raw_row: object,
    context: WorkoutContext,
) -> WorkoutEnergyPoint | None:
    """Map one active-energy point relative to workout start."""

    row = as_raw_dict(raw_row)
    if row is None:
        return None
    timestamp = parse_datetime(row.get("date"))
    if not timestamp:
        return None
    quantity = numeric_value(row.get("qty"))
    if quantity is None:
        return None
    return WorkoutEnergyPoint(
        workout_id=context.header.workout_id,
        offset_sec=_offset_seconds(timestamp, context.start),
        energy_kcal=quantity,
    )


def _map_workout_steps(
    workout: RawDict,
    context: WorkoutContext,
) -> tuple[tuple[WorkoutStepsPoint, ...], int]:
    rows = _recognise_series(workout, "stepCount")
    if rows is None:
        return (), 1
    points: list[WorkoutStepsPoint] = []
    skipped = 0
    for raw_row in rows:
        point = map_workout_steps_row(raw_row, context)
        if point is None:
            skipped += 1
        else:
            points.append(point)
    return tuple(points), skipped


def map_workout_steps_row(
    raw_row: object,
    context: WorkoutContext,
) -> WorkoutStepsPoint | None:
    """Map one step-count point relative to workout start."""

    row = as_raw_dict(raw_row)
    if row is None:
        return None
    timestamp = parse_datetime(row.get("date"))
    if not timestamp:
        return None
    quantity = numeric_value(row.get("qty"))
    if quantity is None:
        return None
    return WorkoutStepsPoint(
        workout_id=context.header.workout_id,
        offset_sec=_offset_seconds(timestamp, context.start),
        steps=quantity,
    )


def _map_workout_recovery(
    workout: RawDict,
    context: WorkoutContext,
) -> tuple[tuple[WorkoutHRRecoveryPoint, ...], int]:
    rows = _recognise_series(workout, "heartRateRecovery")
    if rows is None:
        return (), 1
    points: list[WorkoutHRRecoveryPoint] = []
    skipped = 0
    for raw_row in rows:
        point = map_workout_recovery_row(raw_row, context)
        if point is None:
            skipped += 1
        else:
            points.append(point)
    return tuple(points), skipped


def map_workout_recovery_row(
    raw_row: object,
    context: WorkoutContext,
) -> WorkoutHRRecoveryPoint | None:
    """Map one recovery point relative to workout end."""

    row = as_raw_dict(raw_row)
    if row is None:
        return None
    timestamp = parse_datetime(row.get("date"))
    if not timestamp:
        return None
    heart_rate = normalise_heart_rate(row.get("Min"), row.get("Avg"), row.get("Max"))
    if heart_rate is None:
        return None
    return WorkoutHRRecoveryPoint(
        workout_id=context.header.workout_id,
        offset_sec=_offset_seconds(timestamp, context.end),
        hr_min=heart_rate.minimum,
        hr_avg=int(round(heart_rate.average)),
        hr_max=heart_rate.maximum,
    )


def _offset_seconds(timestamp: datetime, origin: datetime) -> int:
    return int(max(0.0, (timestamp - origin).total_seconds()))


def parse_records(root: object) -> AppleParseOutcome:
    """Run recognition and mapping stages, preserving input order by stream."""

    recognised = recognise_root(root)
    daily_metric_points: list[DailyMetricPoint] = []
    heart_rate_summaries: list[DailyHeartRateSummary] = []
    sleep_summaries: list[DailySleepSummary] = []
    workout_headers: list[WorkoutHeader] = []
    workout_heart_rate: list[WorkoutHRPoint] = []
    workout_steps: list[WorkoutStepsPoint] = []
    workout_energy: list[WorkoutEnergyPoint] = []
    workout_recovery: list[WorkoutHRRecoveryPoint] = []
    skipped_rows = SkippedRows()

    for raw_metric in recognised.metrics:
        mapped_metric = map_metric_record(raw_metric)
        daily_metric_points.extend(mapped_metric.daily_metric_points)
        heart_rate_summaries.extend(mapped_metric.heart_rate_summaries)
        sleep_summaries.extend(mapped_metric.sleep_summaries)
        skipped_rows += mapped_metric.skipped_rows

    for raw_workout in recognised.workouts:
        mapped_workout = map_workout_record(raw_workout)
        workout_headers.extend(mapped_workout.headers)
        workout_heart_rate.extend(mapped_workout.heart_rate_points)
        workout_steps.extend(mapped_workout.step_points)
        workout_energy.extend(mapped_workout.energy_points)
        workout_recovery.extend(mapped_workout.recovery_points)
        skipped_rows += mapped_workout.skipped_rows

    return AppleParseOutcome(
        daily_metric_points=tuple(daily_metric_points),
        heart_rate_summaries=tuple(heart_rate_summaries),
        sleep_summaries=tuple(sleep_summaries),
        workout_headers=tuple(workout_headers),
        workout_heart_rate=tuple(workout_heart_rate),
        workout_steps=tuple(workout_steps),
        workout_energy=tuple(workout_energy),
        workout_recovery=tuple(workout_recovery),
        skipped_rows=skipped_rows,
    )
