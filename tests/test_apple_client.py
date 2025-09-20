import json
from datetime import date
from pathlib import Path
from typing import List, Tuple
from zipfile import ZipFile

from pete_e.infrastructure.apple_client import process_apple_health_export


class StubDal:
    def __init__(self) -> None:
        self.saved: List[Tuple[date, dict]] = []

    def save_apple_daily(self, day: date, metrics: dict) -> None:  # pragma: no cover - interface hook
        self.saved.append((day, metrics))


def _make_zip(tmp_path: Path, filename: str, payload: object) -> Path:
    archive = tmp_path / "apple_export.zip"
    with ZipFile(archive, "w") as zf:
        zf.writestr(filename, json.dumps(payload))
    return archive


def test_process_apple_health_export_single_day(tmp_path: Path) -> None:
    payload = {
        "source": "apple_shortcut",
        "date": "2025-08-27",
        "timezone": "Europe/London",
        "steps": 2948,
        "hr_min": 47,
        "hr_max": 120,
        "hr_avg": 60,
        "hr_resting": 50,
        "exercise_minutes": 6,
        "calories_active": 343,
        "calories_resting": 1999,
        "calories_total": 2342,
        "stand_minutes": 55,
        "distance_m": 2166,
        "sleep_minutes": {
            "asleep": 362,
            "awake": 7,
            "core": 218,
            "deep": 54,
            "in_bed": 369,
            "rem": 90,
        },
    }

    archive = _make_zip(tmp_path, "health.json", payload)
    dal = StubDal()

    processed = process_apple_health_export(str(archive), dal=dal)

    assert processed == 1
    assert len(dal.saved) == 1
    saved_date, metrics = dal.saved[0]
    assert saved_date.isoformat() == payload["date"]
    assert metrics["steps"] == payload["steps"]
    assert metrics["hr_resting"] == payload["hr_resting"]
    assert metrics["sleep_total_minutes"] == payload["sleep_minutes"]["in_bed"]


def test_process_apple_health_export_nested_payloads(tmp_path: Path) -> None:
    payload = {
        "data": [
            {
                "summary_date": "2025-08-28T00:00:00Z",
                "activity": {"steps": "3210", "exercise_minutes": "10"},
                "calories": {"active": "220", "resting": "1500", "total": "1720"},
                "heart_rate": {"min": "45", "max": "110", "avg": "70", "resting": "55"},
                "distance": {"km": "5.5"},
                "sleep": {"minutes": {"asleep": "360", "awake": "30"}},
            },
            {
                "summary_date": "2025-08-29",
                "steps": 4000,
                "exercise_minutes": 12,
                "calories_active": 300,
                "calories_resting": 1600,
                "heart_rate": {"min": 50, "max": 115, "avg": 68, "resting": 52},
                "sleep_minutes": {"asleep": 390, "awake": 20, "rem": 80, "deep": 70, "core": 240},
            },
        ]
    }

    archive = _make_zip(tmp_path, "nested.json", payload)
    dal = StubDal()

    processed = process_apple_health_export(str(archive), dal=dal)

    assert processed == 2
    saved_dates = {d.isoformat(): metrics for d, metrics in dal.saved}

    first_metrics = saved_dates["2025-08-28"]
    assert first_metrics["steps"] == 3210
    assert first_metrics["exercise_minutes"] == 10
    assert first_metrics["calories_active"] == 220
    assert first_metrics["calories_resting"] == 1500
    assert first_metrics["distance_m"] == 5500
    assert first_metrics["sleep_total_minutes"] == 390

    second_metrics = saved_dates["2025-08-29"]
    assert second_metrics["sleep_total_minutes"] == 410  # asleep + awake fallback
    assert second_metrics["sleep_rem_minutes"] == 80
    assert second_metrics["sleep_deep_minutes"] == 70
