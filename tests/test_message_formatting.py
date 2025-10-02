from datetime import date

import pytest
from mocks.pydantic_mock import SecretStr

from pete_e.domain import narrative_builder
from pete_e.domain.narrative_builder import NarrativeBuilder
from pete_e.infrastructure import telegram_sender
from pete_e.config import settings


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
    return deterministic


def test_daily_summary_uses_coach_voice(fixed_random, monkeypatch):
    monkeypatch.setattr(narrative_builder, "phrase_for", lambda **_: "Consistency is queen, volume is king!")

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

    builder = NarrativeBuilder()
    message = builder.build_daily_summary(summary_data)

    expected = "\n".join(
        [
            "Yo Ric! Coach Pete sliding into your DMs 💥",
            "",
            "*Tuesday 03 Sep: Daily Flex*",
            "- Weight: 82.4 kg",
            "- Body fat: 18.3%",
            "- Muscle: 41.5%",
            "- Hydration: 55.0%",
            "- Resting HR: 52 bpm",
            "- Steps: 10,567 struts",
            "- Active burn: 843 kcal",
            "- Sleep: 6h 52m logged",
            "Coach's call: Primed - Keep the pace steady.",
            "Consistency is queen, volume is king!",
        ]
    )

    assert message == expected




def test_daily_summary_formats_extended_metrics(fixed_random, monkeypatch):
    monkeypatch.setattr(
        narrative_builder,
        "phrase_for",
        lambda **_: "Consistency is queen, volume is king!",
    )

    summary_data = {
        "date": date(2024, 9, 4),
        "body_age_years": 31.4,
        "body_age_delta_years": -2.3,
        "hr_resting": 50,
        "hr_avg": 68,
        "hr_max": 154,
        "hr_min": 44,
        "walking_hr_avg": 102,
        "cardio_recovery": 14.6,
        "respiratory_rate": 15.3,
        "blood_oxygen_saturation": 97.8,
        "wrist_temperature": 32.2,
        "hrv_sdnn_ms": 95,
        "vo2_max": 49.1,
        "steps": 12345,
        "distance_m": 8570,
        "flights_climbed": 18,
        "exercise_minutes": 62,
        "calories_active": 850,
        "calories_resting": 1760,
        "stand_minutes": 750,
        "time_in_daylight": 95,
        "strength_volume_kg": 12450,
        "sleep_total_minutes": 440,
        "sleep_asleep_minutes": 420,
        "sleep_rem_minutes": 110,
        "sleep_deep_minutes": 90,
        "sleep_core_minutes": 220,
        "sleep_awake_minutes": 35,
        "readiness_headline": "Ready",
    }

    builder = NarrativeBuilder()
    message = builder.build_daily_summary(summary_data)

    bullet_lines = [line for line in message.split("\n") if line.startswith("- ")]
    expected_lines = [
        "- Body age: 31.4 yr",
        "- Body age delta: -2.3 yr",
        "- Resting HR: 50 bpm",
        "- Avg HR: 68 bpm",
        "- Max HR: 154 bpm",
        "- Min HR: 44 bpm",
        "- Walking HR avg: 102 bpm",
        "- Cardio recovery: 14.6 bpm",
        "- Respiratory rate: 15.3 breaths/min",
        "- SpO2: 97.8%",
        "- Wrist temp: 32.2 degC",
        "- HRV: 95 ms",
        "- VO2max: 49.1 ml/kg/min",
        "- Steps: 12,345 struts",
        "- Distance: 8.57 km covered",
        "- Flights climbed: 18",
        "- Exercise: 62 min logged",
        "- Active burn: 850 kcal",
        "- Resting burn: 1,760 kcal",
        "- Stand: 750 min upright",
        "- Daylight: 95 min outside",
        "- Strength volume: 12,450 kg moved",
        "- Sleep total: 7h 20m",
        "- Sleep: 7h logged",
        "- REM sleep: 1h 50m",
        "- Deep sleep: 1h 30m",
        "- Core sleep: 3h 40m",
        "- Awake: 35m",
    ]

    assert bullet_lines == expected_lines


def test_send_message_sends_plain_text(monkeypatch):
    payload = {}

    def fake_post(url, *, json, timeout):
        payload["url"] = url
        payload["json"] = json

        class _Reply:
            def raise_for_status(self):
                return None

        return _Reply()

    monkeypatch.setattr("pete_e.infrastructure.telegram_sender.requests.post", fake_post)
    monkeypatch.setattr(settings, "TELEGRAM_TOKEN", SecretStr("abc123"))
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "chat-42")

    text = "Weight: 80.5kg (PR #1)! Gains + smiles."
    assert telegram_sender.send_message(text) is True

    assert payload["json"] == {"chat_id": "chat-42", "text": text}
