from datetime import date

import pytest

from pete_e.domain import narrative_builder
from pete_e.domain.narrative_builder import NarrativeBuilder


class _DeterministicRandom:
    def choice(self, seq):
        if not seq:
            raise ValueError('choice sequence was empty')
        return seq[0]

    def randint(self, a, b):
        return a

    def random(self):
        return 0.0


@pytest.fixture
def fixed_random(monkeypatch):
    deterministic = _DeterministicRandom()
    monkeypatch.setattr(narrative_builder, 'random', deterministic)
    monkeypatch.setattr(narrative_builder.narrative_utils.random, 'random', lambda: 0.0)
    monkeypatch.setattr(narrative_builder.narrative_utils.random, 'choice', lambda seq: seq[0])
    return deterministic


@pytest.fixture(autouse=True)
def stub_phrase_picker(monkeypatch):
    monkeypatch.setattr(narrative_builder, 'phrase_for', lambda *_, **__: 'Consistency is queen, volume is king!')


def _base_summary():
    return {
        'date': date(2025, 9, 20),
        'weight_kg': 82.0,
        'body_fat_pct': 18.5,
        'muscle_pct': 41.8,
        'water_pct': 55.2,
        'hr_resting': 52,
        'steps': 9800,
        'calories_active': 760,
        'sleep_asleep_minutes': 420,
        'readiness_headline': 'Primed',
        'readiness_tip': 'Keep the pace steady.',
    }


def test_daily_summary_includes_environment_colour(fixed_random):
    summary_data = _base_summary()
    summary_data.update({
        'environment_temp_degc': 18.6,
        'environment_humidity_percent': 64.2,
    })

    message = NarrativeBuilder().build_daily_summary(summary_data)

    expected_line = '- Environment: 18.6 degC and 64% humidity reported for the workout.'
    assert expected_line in message.splitlines()


def test_daily_summary_skips_environment_when_absent(fixed_random):
    summary_data = _base_summary()
    message = NarrativeBuilder().build_daily_summary(summary_data)

    assert all('Environment:' not in line for line in message.splitlines())
