from datetime import date, datetime, timedelta

import pytest

from pete_e.cli import messenger
from pete_e.domain import body_age, narrative_builder
from pete_e.infrastructure.apple_parser import AppleHealthParser


class _DeterministicRandom:
    def choice(self, seq):
        if not seq:
            raise ValueError("sequence was empty")
        return seq[0]

    def randint(self, a, b):
        return a

    def random(self):
        return 0.0


@pytest.fixture
def fixed_random(monkeypatch):
    deterministic = _DeterministicRandom()
    monkeypatch.setattr(narrative_builder, "random", deterministic)
    monkeypatch.setattr(narrative_builder.narrative_utils.random, "random", lambda: 0.99)
    monkeypatch.setattr(narrative_builder.narrative_utils.random, "choice", lambda seq: seq[0])
    return deterministic


@pytest.fixture(autouse=True)
def stub_phrase_picker(monkeypatch):
    monkeypatch.setattr(narrative_builder, "phrase_for", lambda *_, **__: "Keep rolling!")


def test_apple_parser_maps_hrv_and_vo2_metrics():
    parser = AppleHealthParser()
    payload = {
        "data": {
            "metrics": [
                {
                    "name": "heart_rate_variability_sdnn",
                    "units": "ms",
                    "data": [
                        {"date": "2025-09-18 23:00:00 +0000", "source": "Watch", "qty": "74.1"},
                        {"date": "2025-09-19 23:00:00 +0000", "source": "Watch", "qty": None},
                    ],
                },
                {
                    "name": "vo2max",
                    "units": "ml/kg/min",
                    "data": [
                        {"date": "2025-09-18 12:00:00 +0000", "source": "Watch", "qty": 51.3},
                    ],
                },
            ],
            "workouts": [],
        }
    }

    parsed = parser.parse(payload)

    metric_points = {(p.metric_name, p.unit, round(p.value, 1)) for p in parsed["daily_metric_points"]}
    assert ("hrv_sdnn_ms", "ms", 74.1) in metric_points
    assert ("vo2_max", "ml/kg/min", 51.3) in metric_points


def test_daily_summary_appends_hrv_trend_line(monkeypatch, fixed_random):
    monkeypatch.setattr(body_age, "get_body_age_trend", lambda *_, **__: None)

    target = date(2025, 9, 21)

    class StubDal:
        def get_historical_metrics(self, days: int):
            base_day = target
            rows = []
            for offset, value in enumerate([72.0, 69.0, 69.0, 69.0, 69.0, 69.0, 69.0]):
                rows.append({
                    "date": base_day - timedelta(days=offset),
                    "hrv_sdnn_ms": value,
                })
            return rows

    class StubOrchestrator:
        def __init__(self):
            self.dal = StubDal()
            self.queries = []

        def get_daily_summary(self, target_date=None):
            self.queries.append(target_date)
            return "Base daily summary"

    orch = StubOrchestrator()

    summary = messenger.build_daily_summary(orchestrator=orch, target_date=target)

    assert "Base daily summary" in summary
    assert "HRV:" in summary
    assert "↗" in summary
    assert "69" in summary  # rolling average reference
    assert orch.queries == [target]


def test_body_age_uses_direct_vo2_max(monkeypatch):
    profile = {"birth_date": date(1985, 5, 1).isoformat()}
    apple_history = [
        {"date": date(2025, 9, 19), "vo2_max": 50.0},
        {"date": date(2025, 9, 20), "vo2_max": 51.0},
    ]

    result = body_age.calculate_body_age(withings_history=[], apple_history=apple_history, profile=profile)

    assert result["assumptions"]["used_vo2max_direct"] is True
    assert result["subscores"]["crf"] > 0

