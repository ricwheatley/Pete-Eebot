from datetime import date

import pytest
from pydantic import SecretStr

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
            "- Resting HR: 52 bpm",
            "- Steps: 10,567 struts",
            "- Active burn: 843 kcal",
            "- Sleep: 6h 52m logged",
            "Coach's call: Primed - Keep the pace steady.",
            "Consistency is queen, volume is king!",
        ]
    )

    assert message == expected


def test_send_message_escapes_markdown_v2(monkeypatch):
    payload = {}

    def fake_post(url, *, json, timeout):
        payload["url"] = url
        payload["json"] = json

        class _Reply:
            def raise_for_status(self):
                return None

        return _Reply()

    monkeypatch.setattr(telegram_sender.requests, "post", fake_post)
    monkeypatch.setattr(settings, "TELEGRAM_TOKEN", SecretStr("abc123"))
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "chat-42")

    text = "Weight: 80.5kg (PR #1)! Gains + smiles."
    assert telegram_sender.send_message(text) is True

    assert payload["json"]["parse_mode"] == "MarkdownV2"
    assert payload["json"]["text"] == r"Weight: 80\.5kg \(PR \#1\)\! Gains \+ smiles\."
