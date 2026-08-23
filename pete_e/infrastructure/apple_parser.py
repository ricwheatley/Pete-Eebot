"""Public compatibility adapter for Apple Health JSON parsing."""

from __future__ import annotations

from pete_e.infrastructure import log_utils
from pete_e.infrastructure.apple_parser_normalization import (
    as_raw_dict,
    extract_measure,
    extract_unit,
    normalise_humidity,
    normalise_temperature,
    normalise_workout_environment,
    numeric_value,
    parse_datetime,
)
from pete_e.infrastructure.apple_parser_stages import (
    CANONICAL_METRIC_NAME,
    SKIP_METRICS,
    canonical_metric_name,
    parse_records,
)
from pete_e.infrastructure.apple_parser_types import (
    AppleParseResult,
    DailyHeartRateSummary,
    DailyMetricPoint,
    DailySleepSummary,
    WorkoutEnergyPoint,
    WorkoutHeader,
    WorkoutHRPoint,
    WorkoutHRRecoveryPoint,
    WorkoutStepsPoint,
)


class AppleHealthParser:
    """Parse a HealthAutoExport JSON document into domain rows for persistence."""

    _parse_dt = staticmethod(parse_datetime)
    _canon_metric_name = staticmethod(canonical_metric_name)
    _get_numeric_value = staticmethod(numeric_value)
    _extract_unit = staticmethod(extract_unit)
    _extract_measure = staticmethod(extract_measure)
    _normalise_temperature = staticmethod(normalise_temperature)
    _normalise_humidity = staticmethod(normalise_humidity)

    @staticmethod
    def _extract_workout_environment(
        workout: object,
    ) -> tuple[float | None, float | None]:
        """Retain the legacy helper result while delegating to the typed stage."""

        workout_mapping = as_raw_dict(workout)
        if workout_mapping is None:
            return None, None
        environment = normalise_workout_environment(workout_mapping)
        return environment.temperature_degc, environment.humidity_percent

    def parse(self, root: object) -> AppleParseResult:
        """Return the stable nine-key façade assembled from typed parse stages."""

        outcome = parse_records(root)
        warning = outcome.skipped_rows.warning_message()
        if warning is not None:
            log_utils.log_message(warning, "WARN")
        return outcome.as_legacy_result()


__all__ = [
    "AppleHealthParser",
    "AppleParseResult",
    "CANONICAL_METRIC_NAME",
    "DailyHeartRateSummary",
    "DailyMetricPoint",
    "DailySleepSummary",
    "SKIP_METRICS",
    "WorkoutEnergyPoint",
    "WorkoutHeader",
    "WorkoutHRPoint",
    "WorkoutHRRecoveryPoint",
    "WorkoutStepsPoint",
]
