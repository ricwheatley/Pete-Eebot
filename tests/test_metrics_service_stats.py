"""Focused tests for statistics helpers in :mod:`pete_e.domain.metrics_service`."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from pete_e.domain import metrics_service
from tests import config_stub  # noqa: F401 - ensure stub settings loaded


@pytest.fixture
def sample_series():
    start = date(2024, 1, 1)
    values = [float(n) for n in range(1, 11)]  # 1..10
    return {start + timedelta(days=idx): value for idx, value in enumerate(values)}


def test_calculate_moving_averages(sample_series):
    reference = date(2024, 1, 11)
    averages = metrics_service._calculate_moving_averages(sample_series, reference=reference)

    assert averages["yesterday_value"] == pytest.approx(10.0)
    assert averages["day_before_value"] == pytest.approx(9.0)
    assert averages["avg_7d"] == pytest.approx(sum(range(4, 11)) / 7)
    assert averages["avg_14d"] == pytest.approx(sum(range(1, 11)) / 10)
    assert averages["avg_28d"] == pytest.approx(sum(range(1, 11)) / 10)
    assert averages["avg_90d"] == pytest.approx(sum(range(1, 11)) / 10)


def test_find_historical_extremes(sample_series):
    reference = date(2024, 1, 11)
    extremes = metrics_service._find_historical_extremes(sample_series, reference=reference)

    assert extremes["three_month_high"] == pytest.approx(10.0)
    assert extremes["three_month_low"] == pytest.approx(1.0)
    assert extremes["six_month_high"] == pytest.approx(10.0)
    assert extremes["six_month_low"] == pytest.approx(1.0)
    assert extremes["all_time_high"] == pytest.approx(10.0)
    assert extremes["all_time_low"] == pytest.approx(1.0)


def test_build_metric_stats_coerces_to_floats(sample_series):
    reference = date(2024, 1, 11)
    stats = metrics_service._build_metric_stats(sample_series, reference=reference)

    assert stats["pct_change_d1"] == pytest.approx((10.0 - 9.0) / 9.0 * 100.0)
    assert stats["pct_change_7d"] == pytest.approx(((sum(range(4, 11)) / 7) - (sum(range(1, 11)) / 10)) / (sum(range(1, 11)) / 10) * 100.0)
    assert stats["all_time_high"] == pytest.approx(10.0)
    assert stats["all_time_low"] == pytest.approx(1.0)


def test_get_metrics_overview_integration(monkeypatch):
    class DummyDal:
        def __init__(self):
            self.calls = []

        def get_historical_data(self, start, end):
            self.calls.append((start, end))
            base = date(2024, 1, 1)
            rows = []
            for offset in range(10):
                rows.append(
                    {
                        "date": base + timedelta(days=offset),
                        "weight_kg": 80 + offset,
                        "steps": 1000 + offset * 100,
                    }
                )
            return rows

    dummy = DummyDal()
    overview = metrics_service.get_metrics_overview(dummy, reference_date=date(2024, 1, 11))

    assert "weight" in overview
    assert overview["weight"]["yesterday_value"] == pytest.approx(89.0)
    assert overview["steps"]["yesterday_value"] == pytest.approx(1900.0)
    # Ensure values are coerced to floats even for integers.
    assert isinstance(overview["steps"]["avg_7d"], float)
