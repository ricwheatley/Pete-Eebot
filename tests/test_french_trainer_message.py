"""Tests for the deterministic construction of French trainer messages."""
from __future__ import annotations

import pytest

from pete_e.domain import french_trainer
from pete_e.domain.french_trainer import compose_daily_message
from tests import config_stub  # noqa: F401 - ensure stub settings loaded


@pytest.fixture(autouse=True)
def deterministic_phrase(monkeypatch):
    monkeypatch.setattr(
        french_trainer.phrase_picker,
        "random_phrase",
        lambda kind="motivational", mode="balanced", tags=None: "Garde le cap",
    )


def test_compose_daily_message_includes_highlights_and_context():
    metrics = {
        "weight": {
            "yesterday_value": 80.0,
            "pct_change_d1": -1.2,
            "all_time_low": 80.0,
        },
        "steps": {
            "yesterday_value": 12000,
            "abs_change_d1": 500,
            "three_month_high": 12000,
        },
    }
    context = {"user_name": "Ric", "today_session_type": "Upper Body"}

    message = compose_daily_message(metrics, context)

    assert message.startswith("Bonjour Ric!")
    assert "**Weight:**" in message
    assert "**Steps:**" in message
    assert "Aujourd'hui: Upper Body." in message
    assert message.endswith("Pierre dit: Garde le cap!")


def test_compose_daily_message_handles_missing_metrics():
    message = compose_daily_message({}, {"user_name": "Alex"})
    assert "Pas de donnees" in message
