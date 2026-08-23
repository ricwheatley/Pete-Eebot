from __future__ import annotations

from datetime import datetime, timezone

import pytest

from pete_e.infrastructure.apple_parser import AppleHealthParser
from pete_e.infrastructure.apple_parser_normalization import (
    HeartRateValues,
    WorkoutEnvironment,
    as_raw_dict,
    as_raw_list,
    extract_measure,
    extract_unit,
    normalise_heart_rate,
    normalise_humidity,
    normalise_temperature,
    normalise_workout_environment,
    numeric_value,
    parse_datetime,
)
from pete_e.infrastructure.apple_parser_stages import (
    RecognisedRoot,
    WorkoutContext,
    canonical_metric_name,
    map_daily_heart_rate_row,
    map_daily_metric_row,
    map_daily_sleep_row,
    map_metric_record,
    map_workout_energy_row,
    map_workout_header,
    map_workout_heart_rate_row,
    map_workout_recovery_row,
    map_workout_record,
    map_workout_steps_row,
    parse_records,
    recognise_root,
    select_workout_device,
)
from pete_e.infrastructure.apple_parser_types import (
    DailyMetricPoint,
    SkippedRows,
    WorkoutHeader,
)


UTC = timezone.utc
START = datetime(2024, 7, 1, 7, tzinfo=UTC)
END = datetime(2024, 7, 1, 8, tzinfo=UTC)


def _context() -> WorkoutContext:
    return WorkoutContext(
        header=WorkoutHeader(
            workout_id="stage-workout",
            type_name="Run",
            device_name="Stage Watch",
            start_time=START,
            end_time=END,
            duration_sec=3600.0,
            location=None,
            total_distance_km=None,
            total_active_energy_kj=None,
            avg_intensity=None,
            elevation_gain_m=None,
            environment_temp_degc=None,
            environment_humidity_percent=None,
        ),
        start=START,
        end=END,
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        (object(), None),
        (b"12", None),
        (bytearray(b"12"), None),
        ("", None),
        ("   ", None),
        ("12", 12.0),
        (" -12.5 units", -12.5),
        ("not numeric", None),
        (True, 1.0),
        ([], None),
        ([None, "bad", {"amount": 4}], 4.0),
        ({}, None),
        ({"qty": None, "number": "bad", "data": {"doubleValue": 3}}, 3.0),
    ],
)
def test_numeric_value_covers_scalar_wrapper_and_iterable_shapes(
    raw: object,
    expected: float | None,
) -> None:
    assert numeric_value(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        (1, None),
        ("", None),
        ("unknown", None),
        ("70 degF", "degF"),
        ("20 celsius", "degC"),
        ("45 pct", "%"),
        ("0.45 fraction", "ratio"),
        ({"unit": 1, "unitName": "  ", "unitSymbol": " F "}, "F"),
        ({"value": {"unit": "degC"}}, "degC"),
        ({"value": None, "measurement": {"unitString": "%"}}, "%"),
        ({"value": {}, "measurement": {}}, None),
    ],
)
def test_extract_unit_covers_explicit_inferred_nested_and_unknown_shapes(
    raw: object,
    expected: str | None,
) -> None:
    assert extract_unit(raw) == expected


def test_scalar_normalisers_preserve_none_conversion_and_clamping_inputs() -> None:
    assert extract_measure(None) == (None, None)
    assert extract_measure({"value": "68 F", "unit": "degF"}) == (68.0, "degF")
    assert normalise_temperature(None, "degF") is None
    assert normalise_temperature(10, "unknown") == 10
    assert normalise_temperature(68, " F ") == 20
    assert normalise_humidity(None, "ratio") is None
    assert normalise_humidity(0.5, "ratio") == 50
    assert normalise_humidity(0.5, "percent") == 0.5
    assert normalise_humidity(0.5, None) == 50
    assert normalise_humidity(2, None) == 2
    assert normalise_heart_rate(None, 60, 70) is None
    assert normalise_heart_rate(49.6, 120, 100.4) == HeartRateValues(50, 100, 100)


def test_timestamp_and_raw_shape_recognition_are_narrow_and_legacy_compatible() -> None:
    assert as_raw_dict([]) is None
    assert as_raw_dict({"key": "value"}) == {"key": "value"}
    assert as_raw_list(()) is None
    assert as_raw_list([1]) == [1]
    assert parse_datetime(None) is None
    assert parse_datetime("2024-07-01 08:00:00 +0000") == datetime(
        2024, 7, 1, 8, tzinfo=UTC
    )
    with pytest.raises(ValueError):
        parse_datetime("bad")

    assert recognise_root(None) == RecognisedRoot((), ())
    assert recognise_root({"data": []}) == RecognisedRoot((), ())
    assert recognise_root(
        {"data": {"metrics": [1], "workouts": [2]}}
    ) == RecognisedRoot((1,), (2,))
    assert recognise_root(
        {"data": {"metrics": {}, "workouts": None}}
    ) == RecognisedRoot((), ())


def test_environment_stage_ignores_bad_candidates_and_uses_metadata_fallbacks() -> None:
    environment = normalise_workout_environment(
        {
            "attemptTemperature": 999,
            "temperatureTimestamp": 999,
            "ambientTemperature": "bad",
            "environment": {"temperature": "bad", "humidity": "bad"},
            "weather": {"temperature": "68 F", "humidity": "bad"},
            "metadataEntries": [
                7,
                {},
                {"key": "unused"},
                {"key": "temperature", "value": "bad"},
                {
                    "key": "temperature",
                    "numberValue": 77,
                    "unitName": "F",
                },
                {
                    "name": "humidity",
                    "qty": 0.4,
                    "unitString": "ratio",
                },
            ],
        }
    )

    assert environment == WorkoutEnvironment(20.0, 40.0)
    assert normalise_workout_environment(
        {"metadataEntries": "wrong"}
    ) == WorkoutEnvironment(None, None)
    assert normalise_workout_environment(
        {"metadataEntries": [{"key": "temperature", "value": "bad"}]}
    ) == WorkoutEnvironment(None, None)


def test_environment_metadata_if_elif_prevents_one_entry_filling_both_values() -> None:
    environment = normalise_workout_environment(
        {
            "metadataEntries": [
                {
                    "key": "temperature humidity",
                    "value": 20,
                    "unit": "degC",
                }
            ]
        }
    )

    assert environment == WorkoutEnvironment(20.0, None)


def test_metric_stage_maps_supported_rows_and_classifies_container_errors() -> None:
    assert canonical_metric_name("vo2max") == "vo2_max"
    assert canonical_metric_name("unknown") == "unknown"
    assert map_metric_record(None).skipped_rows == SkippedRows(metric_rows=1)
    assert map_metric_record({"name": ""}).skipped_rows == SkippedRows()
    assert map_metric_record({"name": "weight_body_mass", "data": None}) == (
        map_metric_record({"name": "weight_body_mass"})
    )
    assert map_metric_record({"name": "metric", "data": None}).skipped_rows == (
        SkippedRows(metric_rows=1)
    )
    assert map_metric_record(
        {"name": "heart_rate", "data": None}
    ).skipped_rows == SkippedRows(heart_rate_entries=1)
    assert map_metric_record(
        {"name": "sleep_analysis", "data": None}
    ).skipped_rows == SkippedRows(sleep_entries=1)

    mapped = map_metric_record(
        {
            "name": "vo2max",
            "units": "ml/kg/min",
            "data": [
                None,
                {
                    "date": "2024-07-01 08:00:00 +0000",
                    "source": "Stage Watch",
                    "qty": 51,
                },
            ],
        }
    )
    assert mapped.daily_metric_points == (
        DailyMetricPoint(
            START.replace(hour=8), "Stage Watch", "vo2_max", "ml/kg/min", 51.0
        ),
    )
    assert mapped.skipped_rows == SkippedRows(metric_rows=1)


@pytest.mark.parametrize(
    "mapper",
    [
        map_daily_heart_rate_row,
        lambda raw: map_daily_metric_row(raw, "steps", "count"),
        map_daily_sleep_row,
    ],
)
def test_daily_row_stages_reject_non_objects(mapper) -> None:
    assert mapper(None) is None


def test_daily_row_stages_cover_missing_values_and_sleep_defaults() -> None:
    assert map_daily_heart_rate_row({"date": None}) is None
    assert (
        map_daily_heart_rate_row(
            {
                "date": "2024-07-01 08:00:00 +0000",
                "Min": 50,
                "Avg": None,
                "Max": 70,
            }
        )
        is None
    )
    assert map_daily_metric_row({"date": None}, "steps", "count") is None
    assert (
        map_daily_metric_row(
            {"date": "2024-07-01 08:00:00 +0000", "qty": None},
            "steps",
            "count",
        )
        is None
    )
    assert (
        map_daily_sleep_row(
            {
                "date": "2024-07-01 00:00:00 +0000",
                "sleepStart": None,
                "sleepEnd": "2024-07-01 08:00:00 +0000",
            }
        )
        is None
    )


def test_workout_stage_classifies_header_and_non_list_series_errors() -> None:
    assert map_workout_record(None).skipped_rows == SkippedRows(workout_headers=1)
    assert map_workout_header({}) is None
    mapped = map_workout_record(
        {
            "id": "stage-workout",
            "start": "2024-07-01 07:00:00 +0000",
            "end": "2024-07-01 08:00:00 +0000",
            "heartRateData": None,
            "activeEnergy": {},
            "stepCount": "wrong",
            "heartRateRecovery": 1,
        }
    )

    assert mapped.skipped_rows == SkippedRows(
        workout_heart_rate_points=1,
        workout_energy_rows=1,
        workout_step_rows=1,
        workout_recovery_rows=1,
    )


def test_workout_device_stage_preserves_first_row_preference() -> None:
    assert select_workout_device({}) == "Unknown Device"
    assert (
        select_workout_device(
            {
                "heartRateData": [7],
                "activeEnergy": [{"source": " Energy Sensor "}],
            }
        )
        == "Energy Sensor"
    )
    assert (
        select_workout_device(
            {
                "heartRateData": [{"source": ""}],
                "activeEnergy": [{"source": "ignored"}],
            }
        )
        == "Unknown Device"
    )


@pytest.mark.parametrize(
    "mapper",
    [
        map_workout_heart_rate_row,
        map_workout_energy_row,
        map_workout_steps_row,
        map_workout_recovery_row,
    ],
)
def test_workout_series_row_stages_reject_non_objects(mapper) -> None:
    assert mapper(None, _context()) is None


def test_workout_series_row_stages_cover_date_and_value_errors() -> None:
    context = _context()
    assert map_workout_heart_rate_row({"date": None}, context) is None
    assert (
        map_workout_heart_rate_row(
            {
                "date": "2024-07-01 07:01:00 +0000",
                "Min": 100,
                "Avg": None,
                "Max": 120,
            },
            context,
        )
        is None
    )
    assert map_workout_energy_row({"date": None}, context) is None
    assert (
        map_workout_energy_row(
            {"date": "2024-07-01 07:01:00 +0000", "qty": None}, context
        )
        is None
    )
    assert map_workout_steps_row({"date": None}, context) is None
    assert (
        map_workout_steps_row(
            {"date": "2024-07-01 07:01:00 +0000", "qty": None}, context
        )
        is None
    )
    assert map_workout_recovery_row({"date": None}, context) is None
    assert (
        map_workout_recovery_row(
            {
                "date": "2024-07-01 08:01:00 +0000",
                "Min": 100,
                "Avg": 105,
                "Max": None,
            },
            context,
        )
        is None
    )


def test_parse_records_assembles_typed_outcome_and_adapter_helpers() -> None:
    root = {
        "data": {
            "metrics": [
                {
                    "name": "steps",
                    "units": "count",
                    "data": [{"date": "2024-07-01 08:00:00 +0000", "qty": 1}],
                }
            ],
            "workouts": [None],
        }
    }

    outcome = parse_records(root)

    assert outcome.daily_metric_points[0].value == 1
    assert outcome.skipped_rows == SkippedRows(workout_headers=1)
    assert outcome.as_legacy_result()["skipped_row_count"] == 1
    assert AppleHealthParser._extract_workout_environment(None) == (None, None)
    assert AppleHealthParser._extract_workout_environment(
        {"temperature": "32 F", "humidity": "50 percent"}
    ) == (0.0, 50.0)
