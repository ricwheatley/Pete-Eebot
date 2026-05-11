from __future__ import annotations

from datetime import date, datetime

import pytest

from pete_e.application.exceptions import BadRequestError
from pete_e.application.nutrition_service import NutritionService, build_nutrition_context


class NutritionDal:
    def __init__(self):
        self.inserted = []

    def insert_nutrition_log(self, record):
        self.inserted.append(record)
        row = {
            "id": 10,
            **record,
        }
        return row, False

    def get_nutrition_daily_summary(self, target_date):
        return {
            "local_date": target_date,
            "protein_g": 100,
            "carbs_g": 150,
            "fat_g": 60,
            "alcohol_g": 20,
            "fiber_g": 25,
            "calories_est": 1540,
            "meals_logged": 3,
            "source_breakdown": {"photo_estimate": 3},
            "confidence_breakdown": {"medium": 2, "low": 1},
            "last_logged_at": datetime(2026, 5, 5, 19, 30),
        }

    def get_nutrition_daily_summaries(self, start_date, end_date):
        return [
            {
                "date": start_date,
                "protein_g": 80,
                "carbs_g": 120,
                "fat_g": 50,
                "alcohol_g": None,
                "fiber_g": None,
                "calories_est": 1250,
                "meals_logged": 2,
            },
            {
                "date": end_date,
                "protein_g": 100,
                "carbs_g": 150,
                "fat_g": 60,
                "alcohol_g": 20,
                "fiber_g": 25,
                "calories_est": 1540,
                "meals_logged": 3,
            },
        ]


def test_log_macros_persists_and_shapes_response():
    service = NutritionService(NutritionDal(), timezone_name="Europe/London")

    payload = service.log_macros(
        {
            "protein_g": 40,
            "carbs_g": 65,
            "fat_g": 18,
            "timestamp": "2026-05-05T12:30:00",
            "client_event_id": "evt-1",
        }
    )

    assert payload["id"] == 10
    assert payload["calories_est"] == 582.0
    assert payload["duplicate"] is False
    assert payload["client_event_id"] == "evt-1"


def test_log_macros_raises_bad_request_for_invalid_payload():
    service = NutritionService(NutritionDal(), timezone_name="Europe/London")

    with pytest.raises(BadRequestError):
        service.log_macros({"protein_g": 0, "carbs_g": 0, "fat_g": 0})


def test_daily_summary_shapes_aggregate_payload():
    payload = NutritionService(NutritionDal(), timezone_name="Europe/London").daily_summary("2026-05-05")

    assert payload["date"] == "2026-05-05"
    assert payload["total_protein_g"] == 100
    assert payload["meals_logged"] == 3
    assert payload["total_alcohol_g"] == 20
    assert payload["total_fiber_g"] == 25
    assert payload["data_quality"]["nutrition_data_quality"] == "partial"


def test_build_nutrition_context_returns_trend_metadata():
    payload = build_nutrition_context(NutritionDal(), target_date=date(2026, 5, 5))

    assert payload["data_quality"]["nutrition_data_quality"] == "partial"
    assert payload["last_7d"]["logging_days"] == 1
    assert payload["last_7d"]["avg_alcohol_g"] == 20.0
    assert payload["last_7d"]["avg_fiber_g"] == 25.0
    assert payload["last_7d"]["avg_estimated_calories"] == 1540.0
