from datetime import date, datetime, timedelta

import pytest

from pete_e.cli import messenger
from pete_e.domain import narrative_builder
from pete_e.domain.narrative_builder import NarrativeBuilder


class _DeterministicRandom:
    def choice(self, seq):
        if not seq:
            raise ValueError("choice sequence was empty")
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
    monkeypatch.setattr(narrative_builder, "phrase_for", lambda *_, **__: "Keep composing!")


def test_daily_summary_surfaces_muscle_and_water(fixed_random):
    summary_data = {
        "date": date(2025, 9, 20),
        "weight_kg": 82.0,
        "body_fat_pct": 18.5,
        "muscle_pct": 41.8,
        "water_pct": 55.2,
        "hr_resting": 52,
        "steps": 9800,
        "calories_active": 760,
        "sleep_asleep_minutes": 420,
    }

    message = NarrativeBuilder().build_daily_summary(summary_data)

    assert "- Muscle: 41.8%" in message
    assert "- Hydration: 55.2%" in message


def test_weekly_narrative_mentions_muscle_trend_when_meaningful(fixed_random, monkeypatch):
    fake_today = date(2025, 9, 22)

    class _FixedDateTime:
        @classmethod
        def utcnow(cls):
            return datetime.combine(fake_today, datetime.min.time())

    monkeypatch.setattr(narrative_builder, "datetime", _FixedDateTime)

    days: dict[str, dict] = {}
    for offset in range(1, 8):
        day = fake_today - timedelta(days=offset)
        days[day.isoformat()] = {"body": {"muscle_pct": 42.0}}
    for offset in range(8, 15):
        day = fake_today - timedelta(days=offset)
        days[day.isoformat()] = {"body": {"muscle_pct": 39.5}}

    narrative = narrative_builder.build_weekly_narrative({"days": days})

    assert "Muscle" in narrative
    assert "42.0%" in narrative
    assert "up 2.5%" in narrative

def test_build_daily_summary_includes_muscle_trend_line(monkeypatch):
    monkeypatch.setattr(messenger.body_age, "get_body_age_trend", lambda *_, **__: None)

    target = date(2025, 9, 21)

    class StubDal:
        def __init__(self):
            base = [
                {"date": target - timedelta(days=offset), "muscle_pct": 42.0 if offset < 7 else 39.5}
                for offset in range(14)
            ]
            self.rows = sorted(base, key=lambda row: row["date"])

        def get_historical_metrics(self, days: int):
            return self.rows[-days:] if days <= len(self.rows) else self.rows

    class StubOrchestrator:
        def __init__(self):
            self.dal = StubDal()
            self.requests = []

        def get_daily_summary(self, target_date=None) -> str:
            self.requests.append(target_date)
            return "Base summary"

    orch = StubOrchestrator()
    summary = messenger.build_daily_summary(orchestrator=orch, target_date=target)

    assert "Base summary" in summary
    assert "Muscle trend" in summary
    assert "up 2.5% vs prior" in summary
    assert orch.requests == [target]
