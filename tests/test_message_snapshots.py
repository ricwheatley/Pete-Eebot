from datetime import date, datetime, timedelta

import pytest

from pete_e.domain import narrative_builder, narrative_utils
from pete_e.domain.narrative_builder import NarrativeBuilder


class _DeterministicRandom:
    """Deterministic random stub so snapshot output stays stable."""

    def choice(self, seq):
        if not seq:
            raise ValueError("choice sequence was empty")
        return seq[0]

    def randint(self, a, b):
        return a

    def random(self):
        return 0.42


@pytest.fixture
def snapshot_context(monkeypatch):
    deterministic = _DeterministicRandom()
    monkeypatch.setattr(narrative_builder, "random", deterministic)
    monkeypatch.setattr(narrative_utils, "random", deterministic)

    def fake_phrase(*, tags):
        mapping = {
            "#Motivation": "Consistency is queen, volume is king!",
            "#Humour": "Keep the energy cheeky and the effort honest.",
        }
        return mapping.get(tags[0], "Consistency is queen, volume is king!")

    monkeypatch.setattr(narrative_builder, "phrase_for", fake_phrase)
    return deterministic


def test_daily_message_snapshot(snapshot_context):
    builder = NarrativeBuilder()
    summary_data = {
        "date": date(2024, 9, 3),
        "weight_kg": 82.4,
        "body_fat_pct": 18.3,
        "muscle_pct": 41.5,
        "water_pct": 55.0,
        "hr_resting": 52,
        "steps": 10567,
        "calories_active": 843,
        "sleep_asleep_minutes": 412,
        "readiness_headline": "Primed",
        "readiness_tip": "Keep the pace steady.",
    }

    message = builder.build_daily_summary(summary_data)
    expected = (
        "Yo Ric! Coach Pete sliding into your DMs 💥\n"
        "\n"
        "*Tuesday 03 Sep: Daily Flex*\n"
        "- Weight: 82.4 kg\n"
        "- Body fat: 18.3%\n"
        "- Muscle: 41.5%\n"
        "- Hydration: 55.0%\n"
        "- Resting HR: 52 bpm\n"
        "- Steps: 10,567 struts\n"
        "- Active burn: 843 kcal\n"
        "- Sleep: 6h 52m logged\n"
        "Coach's call: Primed - Keep the pace steady.\n"
        "Consistency is queen, volume is king!"
    )
    assert message == expected


def test_weekly_message_snapshot(snapshot_context, monkeypatch):
    fake_today = date(2024, 9, 10)

    class _FixedDateTime:
        @classmethod
        def utcnow(cls):
            return datetime(fake_today.year, fake_today.month, fake_today.day)

    monkeypatch.setattr(narrative_builder, "datetime", _FixedDateTime)

    metrics = {"days": {}}
    for offset in range(1, 8):
        day = fake_today - timedelta(days=offset)
        metrics["days"][day.strftime("%Y-%m-%d")] = {
            "strength": [
                {"volume_kg": 1500 + offset * 20},
            ],
            "activity": {"steps": 11000 + offset * 150},
            "sleep": {"asleep_minutes": 450 + offset * 6},
            "body": {
                "weight_kg": 82.5 - offset * 0.08,
                "muscle_pct": 41.2 + offset * 0.07,
            },
            "body_age_years": 31.5 - offset * 0.12,
        }

    for offset in range(8, 15):
        day = fake_today - timedelta(days=offset)
        metrics["days"][day.strftime("%Y-%m-%d")] = {
            "strength": [
                {"volume_kg": 1200 + offset * 12},
            ],
            "activity": {"steps": 9500 + offset * 100},
            "sleep": {"asleep_minutes": 410 + offset * 4},
            "body": {
                "weight_kg": 83.4 - offset * 0.05,
                "muscle_pct": 40.6 + offset * 0.04,
            },
            "body_age_years": 32.8 - offset * 0.08,
        }

    message = narrative_builder.build_weekly_narrative(metrics)
    expected = (
        "Howdy Ric 🤠\n\n"
        "Mate, Lifting volume hit 11060kg , up a bit from 9324kg this week. — not bad at all. "
        "mate, You clocked 81200steps this week, up a bit from 74200steps. "
        "mate, Average sleep was 8h per night, about the same as before. "
        "mate, Muscle composition averaged 41.5% this week, up 0.5% from last week. "
        "mate, Body Age averaged 31.0y this week, down 0.9y from last week. "
        "mate, Momentum backdrop - Steps trend: need more data logged (only 14 days in last 30d). "
        "mate, Sleep trend: need more data logged (only 14 days in last 30d). "
        "mate, consistency is queen, volume is king! mate, keep the energy cheeky and the effort honest. "
        "Keep grinding or the gains train leaves without you 🚂💪"
    )
    assert message == expected
