from __future__ import annotations

from typing import List, Tuple

import pytest

from pete_e.application.sync import SyncResult
from pete_e.infrastructure import log_utils
from pete_e.infrastructure.apple_parser import AppleHealthParser


@pytest.fixture()
def capture_logs(monkeypatch):
    calls: List[Tuple[str, str]] = []

    def _fake_log(msg: str, level: str = "INFO") -> None:
        calls.append((msg, level))

    monkeypatch.setattr(log_utils, "log_message", _fake_log)
    return calls


def test_apple_parser_handles_partial_rows_without_crashing(capture_logs):
    parser = AppleHealthParser()
    root = {
        "data": {
            "metrics": [
                {
                    "name": "heart_rate",
                    "units": "count/min",
                    "data": [
                        {
                            "date": "2024-07-01 08:00:00 +0000",
                            "source": "Apple Watch",
                            "Min": None,
                            "Avg": 51,
                            "Max": 63,
                        },
                        {
                            "date": "2024-07-01 08:05:00 +0000",
                            "source": "Apple Watch",
                            "Min": 48,
                            "Avg": 54,
                            "Max": 66,
                        },
                    ],
                },
                {
                    "name": "sleep_analysis",
                    "units": "hr",
                    "data": [
                        {
                            "date": "2024-07-01 00:00:00 +0000",
                            "sleepStart": "2024-07-01 22:15:00 +0000",
                            "sleepEnd": None,
                        },
                        {
                            "date": "2024-07-02 00:00:00 +0000",
                            "source": "Apple Watch",
                            "sleepStart": "2024-07-01 22:45:00 +0000",
                            "sleepEnd": "2024-07-02 06:10:00 +0000",
                            "inBedStart": "2024-07-01 22:30:00 +0000",
                            "inBedEnd": "2024-07-02 06:30:00 +0000",
                            "totalSleep": "7.5",
                            "core": "3.2",
                            "deep": "1.4",
                            "rem": "2.3",
                            "awake": 0.6,
                        },
                    ],
                },
                {
                    "name": "heart_rate_variability",
                    "units": "ms",
                    "data": [
                        {
                            "date": "2024-07-01 00:00:00 +0000",
                            "source": "Apple Watch",
                            "qty": None,
                        },
                        {
                            "date": "2024-07-02 00:00:00 +0000",
                            "source": "Apple Watch",
                            "qty": "82.4",
                        },
                        {
                            "date": "2024-07-03 00:00:00 +0000",
                            "source": "Apple Watch",
                            "qty": "bad-data",
                        },
                    ],
                },
            ],
            "workouts": [
                {
                    "id": "run-01",
                    "name": "Morning Run",
                    "start": "2024-07-01 07:00:00 +0000",
                    "end": "2024-07-01 08:00:00 +0000",
                    "duration": "3600",
                    "location": "Park",
                    "heartRateData": [
                        {
                            "date": "2024-07-01 07:05:00 +0000",
                            "Min": 120,
                            "Avg": 132,
                            "Max": 142,
                            "source": "Apple Watch",
                        },
                        {
                            "date": "2024-07-01 07:06:00 +0000",
                            "Min": None,
                            "Avg": 131,
                            "Max": 141,
                        },
                    ],
                    "activeEnergy": [
                        {
                            "date": "2024-07-01 07:05:00 +0000",
                            "qty": "30",
                        },
                        {
                            "date": "2024-07-01 07:06:00 +0000",
                            "qty": None,
                        },
                    ],
                    "stepCount": [
                        {
                            "date": "2024-07-01 07:05:00 +0000",
                            "qty": "120",
                        },
                        {
                            "date": "2024-07-01 07:06:00 +0000",
                            "qty": "",
                        },
                    ],
                    "heartRateRecovery": [
                        {
                            "date": "2024-07-01 08:02:00 +0000",
                            "Min": 100,
                            "Avg": 104,
                            "Max": 110,
                        },
                        {
                            "date": "2024-07-01 08:03:00 +0000",
                            "Min": 101,
                            "Avg": 104,
                            "Max": None,
                        },
                    ],
                },
                {
                    "id": "",
                    "start": "2024-07-02 07:00:00 +0000",
                    "end": "2024-07-02 07:30:00 +0000",
                },
            ],
        }
    }

    result = parser.parse(root)

    assert len(result["hr_summaries"]) == 1
    assert len(result["sleep_summaries"]) == 1
    assert len(result["daily_metric_points"]) == 1
    assert len(result["workout_headers"]) == 1
    assert len(result["workout_hr"]) == 1
    assert len(result["workout_energy"]) == 1
    assert len(result["workout_steps"]) == 1
    assert len(result["workout_hr_recovery"]) == 1

    warn_messages = [msg for msg, level in capture_logs if level == "WARN"]
    assert warn_messages, "Expected a WARN log about skipped Apple rows"
    warn_text = warn_messages[-1]
    expected_fragments = [
        "metric rows",
        "heart rate entries",
        "sleep entries",
        "workout headers",
        "workout heart-rate points",
        "workout energy rows",
        "workout step rows",
        "workout recovery rows",
    ]
    for fragment in expected_fragments:
        assert fragment in warn_text


def test_sync_result_summary_includes_withings_note():
    result = SyncResult(
        success=False,
        attempts=2,
        failed_sources=["Withings"],
        source_statuses={"AppleDropbox": "ok", "Withings": "failed"},
        label="daily",
        undelivered_alerts=[],
    )

    summary = result.summary_line(days=1)
    lines = summary.splitlines()
    assert lines[0].startswith("Sync summary:")
    assert "Withings=failed" in lines[0]
    assert lines[1] == "Withings data unavailable today"


def test_sync_result_summary_handles_multi_day_window():
    result = SyncResult(
        success=False,
        attempts=1,
        failed_sources=["Withings"],
        source_statuses={"Withings": "failed"},
        label="daily",
        undelivered_alerts=[],
    )

    summary = result.summary_line(days=3)
    lines = summary.splitlines()
    assert lines[-1] == "Withings data unavailable across last 3 days"

