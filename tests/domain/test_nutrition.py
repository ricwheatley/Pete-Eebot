from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from pete_e.domain.nutrition import NutritionValidationError, build_nutrition_log_record


def test_build_nutrition_log_record_defaults_and_calories():
    record = build_nutrition_log_record(
        {
            "protein_g": 40,
            "carbs_g": 65,
            "fat_g": 18,
            "timestamp": "2026-05-05T12:30:00",
        },
        timezone_name="Europe/London",
    )

    assert record.source == "photo_estimate"
    assert record.confidence == "medium"
    assert record.local_date.isoformat() == "2026-05-05"
    assert record.calories_est == Decimal("582.00")


def test_build_nutrition_log_record_uses_now_when_timestamp_missing():
    record = build_nutrition_log_record(
        {"protein_g": 20, "carbs_g": 10, "fat_g": 5},
        timezone_name="Europe/London",
        now=datetime(2026, 5, 5, 8, 15),
    )

    assert record.local_date.isoformat() == "2026-05-05"


def test_build_nutrition_log_record_rejects_invalid_macros():
    with pytest.raises(NutritionValidationError):
        build_nutrition_log_record(
            {"protein_g": -1, "carbs_g": 10, "fat_g": 5},
            timezone_name="Europe/London",
        )


def test_build_nutrition_log_record_warns_for_large_single_entry():
    record = build_nutrition_log_record(
        {
            "protein_g": 90,
            "carbs_g": 200,
            "fat_g": 20,
            "timestamp": "2026-05-05T12:30:00+01:00",
        },
        timezone_name="Europe/London",
    )

    assert "high_protein_single_entry" in record.warnings
    assert "high_carbs_single_entry" in record.warnings

