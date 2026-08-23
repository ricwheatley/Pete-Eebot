from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from pete_e.infrastructure import log_utils
from pete_e.infrastructure.apple_parser import (
    AppleHealthParser,
    DailyHeartRateSummary,
    DailyMetricPoint,
    DailySleepSummary,
    WorkoutEnergyPoint,
    WorkoutHeader,
    WorkoutHRPoint,
    WorkoutHRRecoveryPoint,
    WorkoutStepsPoint,
)
from pete_e.infrastructure.apple_writer import AppleHealthWriter


RESULT_KEYS = [
    "daily_metric_points",
    "hr_summaries",
    "sleep_summaries",
    "workout_headers",
    "workout_hr",
    "workout_steps",
    "workout_energy",
    "workout_hr_recovery",
    "skipped_row_count",
]


@pytest.fixture()
def parser_logs(monkeypatch):
    calls: list[tuple[str, str]] = []

    def capture(message: str, level: str = "INFO") -> None:
        calls.append((message, level))

    monkeypatch.setattr(log_utils, "log_message", capture)
    return calls


def _empty_result() -> dict[str, object]:
    return {
        "daily_metric_points": [],
        "hr_summaries": [],
        "sleep_summaries": [],
        "workout_headers": [],
        "workout_hr": [],
        "workout_steps": [],
        "workout_energy": [],
        "workout_hr_recovery": [],
        "skipped_row_count": 0,
    }


def _valid_workout(**overrides: object) -> dict[str, object]:
    workout: dict[str, object] = {
        "id": "workout-1",
        "name": "Run",
        "start": "2024-07-01 07:00:00 +0000",
        "end": "2024-07-01 08:00:00 +0000",
    }
    workout.update(overrides)
    return workout


def test_parse_maps_every_stream_value_and_preserves_order(parser_logs) -> None:
    root = {
        "data": {
            "metrics": [
                {
                    "name": "walking_running_distance",
                    "units": " km ",
                    "data": [
                        {
                            "date": "2024-07-01 08:00:00 +0130",
                            "source": " Watch A ",
                            "qty": {
                                "measurement": {"data": [None, {"value": "1.25 km"}]}
                            },
                        },
                        {
                            "date": "2024-07-01 09:00:00 +0130",
                            "qty": False,
                        },
                    ],
                },
                {
                    "name": "heart_rate",
                    "units": "count/min",
                    "data": [
                        {
                            "date": "2024-07-01 10:00:00 +0000",
                            "Min": 49.6,
                            "Avg": 120,
                            "Max": 100.4,
                        },
                        {
                            "date": "2024-07-01 11:00:00 -0230",
                            "source": None,
                            "Min": 60.5,
                            "Avg": 40,
                            "Max": 79.5,
                        },
                    ],
                },
                {
                    "name": "sleep_analysis",
                    "units": "hr",
                    "data": [
                        {
                            "date": "2024-07-02 00:00:00 +0000",
                            "source": "",
                            "sleepStart": "2024-07-01 22:30:00 +0100",
                            "sleepEnd": "2024-07-02 06:00:00 +0100",
                            "inBedStart": None,
                            "inBedEnd": "",
                            "totalSleep": "7.5",
                            "core": 0,
                            "deep": {"value": "1.25 hr"},
                            "rem": "bad",
                            "awake": False,
                        }
                    ],
                },
            ],
            "workouts": [
                {
                    "id": "run-1",
                    "name": "",
                    "start": "2024-07-01 07:00:00 +0100",
                    "end": "2024-07-01 08:00:00 +0100",
                    "duration": {"qty": "3600 sec"},
                    "location": 0,
                    "distance": 0,
                    "walkingRunningDistance": 5,
                    "activeEnergyBurned": {"measurement": {"value": "400 kJ"}},
                    "intensity": "7.5 effort",
                    "elevationUp": 12,
                    "temperature": {"value": "68 F", "unit": "degF"},
                    "humidity": {"qty": 0.456, "unit": "ratio"},
                    "environment": {
                        "temperature": {"qty": 99, "unit": "degC"},
                        "humidity": {"qty": 99, "unit": "%"},
                    },
                    "heartRateData": [
                        {
                            "date": "2024-07-01 06:59:00 +0100",
                            "source": " Wrist Watch ",
                            "Min": 120.4,
                            "Avg": 200,
                            "Max": 160.4,
                        },
                        {
                            "date": "2024-07-01 07:05:00 +0100",
                            "Min": 100,
                            "Avg": 110,
                            "Max": 120,
                        },
                    ],
                    "activeEnergy": [
                        {
                            "date": "2024-07-01 07:10:00 +0100",
                            "qty": False,
                        }
                    ],
                    "stepCount": [
                        {
                            "date": "2024-07-01 07:15:00 +0100",
                            "qty": "42 steps",
                        }
                    ],
                    "heartRateRecovery": [
                        {
                            "date": "2024-07-01 08:02:00 +0100",
                            "Min": 100.6,
                            "Avg": 105.5,
                            "Max": 110.4,
                        }
                    ],
                }
            ],
        }
    }

    result = AppleHealthParser().parse(root)

    plus_0130 = timezone(timedelta(hours=1, minutes=30))
    minus_0230 = timezone(-timedelta(hours=2, minutes=30))
    plus_0100 = timezone(timedelta(hours=1))
    assert list(result) == RESULT_KEYS
    assert result == {
        "daily_metric_points": [
            DailyMetricPoint(
                datetime(2024, 7, 1, 8, tzinfo=plus_0130),
                "Watch A",
                "distance_walking_running",
                "km",
                1.25,
            ),
            DailyMetricPoint(
                datetime(2024, 7, 1, 9, tzinfo=plus_0130),
                "Unknown",
                "distance_walking_running",
                "km",
                0.0,
            ),
        ],
        "hr_summaries": [
            DailyHeartRateSummary(
                datetime(2024, 7, 1, 10, tzinfo=timezone.utc),
                "Unknown",
                50,
                100,
                100,
            ),
            DailyHeartRateSummary(
                datetime(2024, 7, 1, 11, tzinfo=minus_0230),
                "None",
                60,
                60,
                80,
            ),
        ],
        "sleep_summaries": [
            DailySleepSummary(
                date=datetime(2024, 7, 2, tzinfo=timezone.utc),
                device_name="",
                sleep_start=datetime(2024, 7, 1, 22, 30, tzinfo=plus_0100),
                sleep_end=datetime(2024, 7, 2, 6, tzinfo=plus_0100),
                in_bed_start=None,
                in_bed_end=None,
                total_sleep_hrs=7.5,
                core_hrs=0.0,
                deep_hrs=1.25,
                rem_hrs=0.0,
                awake_hrs=0.0,
            )
        ],
        "workout_headers": [
            WorkoutHeader(
                workout_id="run-1",
                type_name="Other",
                device_name="Wrist Watch",
                start_time=datetime(2024, 7, 1, 7, tzinfo=plus_0100),
                end_time=datetime(2024, 7, 1, 8, tzinfo=plus_0100),
                duration_sec=3600.0,
                location="0",
                total_distance_km=5.0,
                total_active_energy_kj=400.0,
                avg_intensity=7.5,
                elevation_gain_m=12.0,
                environment_temp_degc=20.0,
                environment_humidity_percent=45.6,
            )
        ],
        "workout_hr": [
            WorkoutHRPoint("run-1", 0, 120, 160, 160),
            WorkoutHRPoint("run-1", 300, 100, 110, 120),
        ],
        "workout_steps": [WorkoutStepsPoint("run-1", 900, 42.0)],
        "workout_energy": [WorkoutEnergyPoint("run-1", 600, 0.0)],
        "workout_hr_recovery": [WorkoutHRRecoveryPoint("run-1", 120, 101, 106, 110)],
        "skipped_row_count": 0,
    }
    assert parser_logs == []


def test_output_dataclasses_keep_the_public_adapter_module_identity() -> None:
    output_types = (
        DailyMetricPoint,
        DailyHeartRateSummary,
        DailySleepSummary,
        WorkoutHeader,
        WorkoutHRPoint,
        WorkoutStepsPoint,
        WorkoutEnergyPoint,
        WorkoutHRRecoveryPoint,
    )

    assert {output_type.__module__ for output_type in output_types} == {
        "pete_e.infrastructure.apple_parser"
    }


@pytest.mark.parametrize(
    "root",
    [
        None,
        [],
        "",
        0,
        False,
        {},
        {"data": None},
        {"data": []},
        {"data": False},
        {"data": {"metrics": None, "workouts": {}}},
        {"data": {"metrics": [], "workouts": []}},
    ],
)
def test_parse_tolerates_existing_empty_and_wrong_container_shapes(
    root: object,
    parser_logs,
) -> None:
    assert AppleHealthParser().parse(root) == _empty_result()
    assert parser_logs == []


def _timestamp_payload(stream: str, timestamp: object) -> dict[str, object]:
    metric_rows: dict[str, object]
    if stream == "metric":
        metric_rows = {
            "metrics": [
                {
                    "name": "step_count",
                    "units": "count",
                    "data": [{"date": timestamp, "qty": 1}],
                }
            ],
            "workouts": [],
        }
    elif stream == "heart rate":
        metric_rows = {
            "metrics": [
                {
                    "name": "heart_rate",
                    "data": [{"date": timestamp, "Min": 50, "Avg": 60, "Max": 70}],
                }
            ],
            "workouts": [],
        }
    elif stream == "sleep":
        metric_rows = {
            "metrics": [
                {
                    "name": "sleep_analysis",
                    "data": [
                        {
                            "date": timestamp,
                            "sleepStart": "2024-07-01 22:00:00 +0000",
                            "sleepEnd": "2024-07-02 06:00:00 +0000",
                        }
                    ],
                }
            ],
            "workouts": [],
        }
    elif stream == "workout header":
        metric_rows = {
            "metrics": [],
            "workouts": [_valid_workout(start=timestamp)],
        }
    else:
        series_key = {
            "workout heart-rate": "heartRateData",
            "workout energy": "activeEnergy",
            "workout steps": "stepCount",
            "workout recovery": "heartRateRecovery",
        }[stream]
        row: dict[str, object] = {"date": timestamp}
        if stream in {"workout heart-rate", "workout recovery"}:
            row.update({"Min": 50, "Avg": 60, "Max": 70})
        else:
            row["qty"] = 1
        metric_rows = {
            "metrics": [],
            "workouts": [_valid_workout(**{series_key: [row]})],
        }
    return {"data": metric_rows}


@pytest.mark.parametrize(
    ("stream", "warning_section"),
    [
        ("metric", "1 metric rows"),
        ("heart rate", "1 heart rate entries"),
        ("sleep", "1 sleep entries"),
        ("workout header", "1 workout headers"),
        ("workout heart-rate", "1 workout heart-rate points"),
        ("workout energy", "1 workout energy rows"),
        ("workout steps", "1 workout step rows"),
        ("workout recovery", "1 workout recovery rows"),
    ],
)
def test_missing_timestamp_is_skipped_in_each_stream(
    stream: str,
    warning_section: str,
    parser_logs,
) -> None:
    result = AppleHealthParser().parse(_timestamp_payload(stream, None))

    assert result["skipped_row_count"] == 1
    assert parser_logs == [
        (
            f"Apple Health parser skipped {warning_section} due to invalid data.",
            "WARN",
        )
    ]


@pytest.mark.parametrize(
    "stream",
    [
        "metric",
        "heart rate",
        "sleep",
        "workout header",
        "workout heart-rate",
        "workout energy",
        "workout steps",
        "workout recovery",
    ],
)
def test_non_empty_malformed_timestamp_aborts_each_stream(
    stream: str,
    parser_logs,
) -> None:
    with pytest.raises(ValueError) as exc_info:
        AppleHealthParser().parse(_timestamp_payload(stream, "not-a-date"))

    assert str(exc_info.value) == (
        "time data 'not-a-date' does not match format '%Y-%m-%d %H:%M:%S %z'"
    )
    assert parser_logs == []


def test_falsey_timestamps_skip_but_truthy_non_string_timestamp_raises(
    parser_logs,
) -> None:
    rows = [{"date": value, "qty": 1} for value in (None, "", 0, False, [], {})]
    result = AppleHealthParser().parse(
        {
            "data": {
                "metrics": [{"name": "step_count", "units": "count", "data": rows}],
                "workouts": [],
            }
        }
    )

    assert result["skipped_row_count"] == 6
    assert parser_logs == [
        (
            "Apple Health parser skipped 6 metric rows due to invalid data.",
            "WARN",
        )
    ]

    with pytest.raises(TypeError) as exc_info:
        AppleHealthParser().parse(_timestamp_payload("metric", 1))
    assert str(exc_info.value) == "strptime() argument 1 must be str, not int"


def test_metric_aliases_recursive_numbers_zero_values_and_skip_policy(
    parser_logs,
) -> None:
    aliases = {
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
    metrics: list[object] = []
    for index, name in enumerate(aliases):
        metrics.append(
            {
                "name": name,
                "units": "mystery-unit",
                "data": [
                    {
                        "date": f"2024-07-{index + 1:02d} 00:00:00 +0000",
                        "source": "Alias Watch",
                        "qty": index + 1,
                    }
                ],
            }
        )
    metrics.extend(
        [
            {
                "name": "unknown_metric",
                "units": "furlongs",
                "data": [
                    {
                        "date": "2024-07-20 00:00:00 +0000",
                        "qty": {
                            "qty": None,
                            "value": {
                                "measurement": {
                                    "data": ["bad", {"amount": "2.5 units"}]
                                }
                            },
                        },
                    },
                    {
                        "date": "2024-07-21 00:00:00 +0000",
                        "qty": [None, {"number": 0}],
                    },
                    {
                        "date": "2024-07-22 00:00:00 +0000",
                        "qty": False,
                    },
                    {
                        "date": "2024-07-23 00:00:00 +0000",
                        "qty": " -3.5widgets",
                    },
                    {
                        "date": "2024-07-24 00:00:00 +0000",
                        "qty": "+4.5widgets",
                    },
                ],
            },
            *(
                {"name": name, "data": "ignored"}
                for name in (
                    "weight_body_mass",
                    "body_fat_percentage",
                    "body_mass_index",
                    "lean_body_mass",
                )
            ),
            {"name": "", "data": "ignored"},
            {"units": "count", "data": "ignored"},
            {"name": "missing_data_is_empty"},
        ]
    )

    result = AppleHealthParser().parse({"data": {"metrics": metrics, "workouts": []}})
    points = result["daily_metric_points"]

    assert [point.metric_name for point in points[: len(aliases)]] == list(
        aliases.values()
    )
    assert [(point.metric_name, point.unit, point.value) for point in points[-4:]] == [
        ("unknown_metric", "furlongs", 2.5),
        ("unknown_metric", "furlongs", 0.0),
        ("unknown_metric", "furlongs", 0.0),
        ("unknown_metric", "furlongs", -3.5),
    ]
    assert result["skipped_row_count"] == 1
    assert parser_logs == [
        (
            "Apple Health parser skipped 1 metric rows due to invalid data.",
            "WARN",
        )
    ]


def test_metric_data_shape_classification_preserves_missing_and_present_falsey_rules(
    parser_logs,
) -> None:
    metrics = [
        7,
        {"name": "ordinary_missing_data"},
        {"name": "ordinary_none", "data": None},
        {"name": "heart_rate"},
        {"name": "heart_rate", "data": None},
        {"name": "sleep_analysis"},
        {"name": "sleep_analysis", "data": {}},
    ]

    result = AppleHealthParser().parse({"data": {"metrics": metrics, "workouts": []}})

    assert result["skipped_row_count"] == 4
    assert parser_logs == [
        (
            "Apple Health parser skipped 2 metric rows, 1 heart rate entries, "
            "1 sleep entries due to invalid data.",
            "WARN",
        )
    ]


def test_workout_environment_layouts_precedence_conversion_and_header_defaults(
    parser_logs,
) -> None:
    workouts = [
        _valid_workout(
            id="direct",
            name="",
            attemptTemperature={"qty": 999, "unit": "degC"},
            temperatureTimestamp={"qty": 999, "unit": "degC"},
            ambientTemperature={"value": "50 F", "unit": "fahrenheit"},
            relativeHumidity={"qty": 0.2},
            environment={
                "temperature": {"qty": 99, "unit": "degC"},
                "humidity": {"qty": 99, "unit": "%"},
            },
            metadataEntries=[
                {"key": "temperature", "value": 88, "unit": "degC"},
                {"key": "humidity", "value": 88, "unit": "%"},
            ],
        ),
        _valid_workout(
            id="environment",
            environment={
                "temperature": {"measurement": {"value": 10}, "unit": "degC"},
                "humidity": {"value": 120, "unitName": "percent"},
            },
        ),
        _valid_workout(
            id="weather",
            name=None,
            weather={
                "temperature": "32 Fahrenheit",
                "humidity": {"value": -0.5, "unit": "ratio"},
            },
        ),
        _valid_workout(
            id="metadata",
            metadataEntries=[
                {
                    "name": "HKWeatherTemperature",
                    "numberValue": 77,
                    "unitName": "F",
                },
                {
                    "key": "humidity",
                    "value": {"qty": 0.55},
                    "unitString": "fraction",
                },
            ],
        ),
        _valid_workout(id="missing", duration=None, location=""),
    ]

    result = AppleHealthParser().parse({"data": {"metrics": [], "workouts": workouts}})
    headers = result["workout_headers"]

    assert [header.workout_id for header in headers] == [
        "direct",
        "environment",
        "weather",
        "metadata",
        "missing",
    ]
    assert [header.type_name for header in headers] == [
        "Other",
        "Run",
        "None",
        "Run",
        "Run",
    ]
    assert [
        (
            header.environment_temp_degc,
            header.environment_humidity_percent,
        )
        for header in headers
    ] == [(10.0, 20.0), (10.0, 100.0), (0.0, 0.0), (25.0, 55.0), (None, None)]
    assert headers[-1].duration_sec == 0.0
    assert headers[-1].location is None
    assert headers[-1].total_distance_km is None
    assert headers[-1].total_active_energy_kj is None
    assert headers[-1].avg_intensity is None
    assert headers[-1].elevation_gain_m is None
    assert parser_logs == []


def test_workout_device_selection_uses_existing_series_preference_and_fallback(
    parser_logs,
) -> None:
    workouts = [
        _valid_workout(
            id="later-series",
            heartRateData=[7],
            activeEnergy=[{"source": " Energy Sensor "}],
        ),
        _valid_workout(
            id="blank-first-source",
            heartRateData=[{"source": ""}],
            activeEnergy=[{"source": "Energy Sensor"}],
        ),
        _valid_workout(id="no-series"),
        _valid_workout(id="missing-source", activeEnergy=[{}]),
    ]

    result = AppleHealthParser().parse({"data": {"metrics": [], "workouts": workouts}})

    assert [header.device_name for header in result["workout_headers"]] == [
        "Energy Sensor",
        "Unknown Device",
        "Unknown Device",
        "Unknown Device",
    ]
    assert result["skipped_row_count"] == 5
    assert parser_logs == [
        (
            "Apple Health parser skipped 2 workout heart-rate points, "
            "3 workout energy rows due to invalid data.",
            "WARN",
        )
    ]


def test_mixed_invalid_rows_preserve_skip_count_warning_order_and_valid_order(
    parser_logs,
) -> None:
    root = {
        "data": {
            "metrics": [
                7,
                {
                    "name": "step_count",
                    "units": "count",
                    "data": [
                        None,
                        {"date": None, "qty": 1},
                        {
                            "date": "2024-07-02 00:00:00 +0000",
                            "qty": 2,
                        },
                        {
                            "date": "2024-07-01 00:00:00 +0000",
                            "qty": 1,
                        },
                    ],
                },
                {"name": "heart_rate", "data": "bad"},
                {"name": "sleep_analysis", "data": [None]},
            ],
            "workouts": [
                None,
                _valid_workout(
                    id="valid-2",
                    heartRateData="bad",
                    activeEnergy=[None],
                    stepCount=[{"date": None, "qty": 1}],
                    heartRateRecovery=[
                        {
                            "date": "2024-07-01 08:01:00 +0000",
                            "Min": 50,
                            "Avg": 60,
                            "Max": None,
                        }
                    ],
                ),
                _valid_workout(id="valid-1"),
            ],
        }
    }

    result = AppleHealthParser().parse(root)

    assert [point.value for point in result["daily_metric_points"]] == [2.0, 1.0]
    assert [header.workout_id for header in result["workout_headers"]] == [
        "valid-2",
        "valid-1",
    ]
    assert result["skipped_row_count"] == 10
    assert parser_logs == [
        (
            "Apple Health parser skipped 3 metric rows, 1 heart rate entries, "
            "1 sleep entries, 1 workout headers, 1 workout heart-rate points, "
            "1 workout energy rows, 1 workout step rows, 1 workout recovery rows "
            "due to invalid data.",
            "WARN",
        )
    ]


def test_parse_output_maps_to_writer_rows_without_shape_translation() -> None:
    class RecordingWriter(AppleHealthWriter):
        def __init__(self) -> None:
            super().__init__(None)  # type: ignore[arg-type]
            self.rows: dict[str, list[dict[str, object]]] = {}

        def _prepare_data_for_bulk_upsert(self, parsed_data: dict) -> None:
            self._device_cache = {"Contract Watch": 11}
            self._metric_type_cache = {"step_count": 22}

        def _execute_many_upsert(
            self,
            table: str,
            conflict_keys: list[str],
            update_keys: list[str],
            data: list[dict],
        ) -> None:
            del conflict_keys, update_keys
            self.rows[table] = data

    parsed = AppleHealthParser().parse(
        {
            "data": {
                "metrics": [
                    {
                        "name": "step_count",
                        "units": "count",
                        "data": [
                            {
                                "date": "2024-07-02 08:00:00 +0100",
                                "source": "Contract Watch",
                                "qty": 123,
                            }
                        ],
                    },
                    {
                        "name": "heart_rate",
                        "data": [
                            {
                                "date": "2024-07-02 09:00:00 +0100",
                                "source": "Contract Watch",
                                "Min": 50,
                                "Avg": 60,
                                "Max": 70,
                            }
                        ],
                    },
                    {
                        "name": "sleep_analysis",
                        "data": [
                            {
                                "date": "2024-07-02 00:00:00 +0100",
                                "source": "Contract Watch",
                                "sleepStart": "2024-07-01 22:00:00 +0100",
                                "sleepEnd": "2024-07-02 06:00:00 +0100",
                                "totalSleep": 8,
                            }
                        ],
                    },
                ],
                "workouts": [],
            }
        }
    )
    writer = RecordingWriter()

    writer.upsert_all(parsed)

    plus_0100 = timezone(timedelta(hours=1))
    assert writer.rows["DailyMetric"] == [
        {
            "metric_id": 22,
            "device_id": 11,
            "date": datetime(2024, 7, 2, 8, tzinfo=plus_0100),
            "value": 123.0,
        }
    ]
    assert writer.rows["DailyHeartRateSummary"] == [
        {
            "device_id": 11,
            "date": datetime(2024, 7, 2).date(),
            "hr_min": 50,
            "hr_avg": 60,
            "hr_max": 70,
        }
    ]
    assert writer.rows["DailySleepSummary"] == [
        {
            "device_id": 11,
            "date": datetime(2024, 7, 2).date(),
            "sleep_start": datetime(2024, 7, 1, 21),
            "sleep_end": datetime(2024, 7, 2, 5),
            "in_bed_start": None,
            "in_bed_end": None,
            "total_sleep_hrs": 8.0,
            "core_hrs": 0.0,
            "deep_hrs": 0.0,
            "rem_hrs": 0.0,
            "awake_hrs": 0.0,
        }
    ]
    assert writer.rows["Workout"] == []
    assert writer.rows["WorkoutHeartRate"] == []
    assert writer.rows["WorkoutStepCount"] == []
    assert writer.rows["WorkoutActiveEnergy"] == []
    assert writer.rows["WorkoutHeartRateRecovery"] == []
