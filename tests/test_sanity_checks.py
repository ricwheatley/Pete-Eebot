from datetime import datetime, timedelta, timezone
import types

import pytest

from pete_e.application import orchestrator as orchestrator_module
from pete_e.application.orchestrator import Orchestrator


class StubDal:
    def __init__(self):
        self.refreshed = False

    def save_withings_daily(self, day, weight_kg, body_fat_pct):
        return None

    def save_wger_log(self, day, exercise_id, set_number, reps, weight_kg, rir):
        return None

    def refresh_actual_view(self):
        self.refreshed = True


class StubWithingsClient:
    def __init__(self):
        self._state = types.SimpleNamespace(requires_reauth=False, reason=None)

    def get_summary(self, days_back):
        return {}

    def get_token_state(self):
        return self._state


class StubWgerClient:
    def get_logs_by_date(self, days):
        return {}


@pytest.fixture(autouse=True)
def stub_dependencies(monkeypatch):
    monkeypatch.setattr(orchestrator_module, "WithingsClient", StubWithingsClient)
    monkeypatch.setattr(orchestrator_module, "WgerClient", StubWgerClient)
    monkeypatch.setattr(Orchestrator, "_recalculate_body_age", lambda self, target_day: None)
    monkeypatch.setattr(
        orchestrator_module,
        "run_apple_health_ingest",
        lambda: types.SimpleNamespace(sources=[], workouts=0, daily_points=0),
        raising=False,
    )
    monkeypatch.setattr(
        orchestrator_module,
        "get_last_successful_import_timestamp",
        lambda: datetime.now(timezone.utc),
        raising=False,
    )


@pytest.fixture
def collect_alerts(monkeypatch):
    alerts = []
    monkeypatch.setattr(
        orchestrator_module.telegram_sender,
        "send_alert",
        lambda message: alerts.append(message),
        raising=False,
    )
    return alerts


def test_alerts_when_apple_import_stale(monkeypatch, collect_alerts):
    stale_time = datetime.now(timezone.utc) - timedelta(days=4)
    monkeypatch.setattr(
        orchestrator_module,
        "get_last_successful_import_timestamp",
        lambda: stale_time,
        raising=False,
    )
    monkeypatch.setattr(
        orchestrator_module.settings,
        "APPLE_MAX_STALE_DAYS",
        3,
        raising=False,
    )

    orch = Orchestrator(dal=StubDal())
    orch.run_daily_sync(days=1)

    assert collect_alerts, "Expected a Telegram alert when Apple imports are stale"
    assert "Apple" in collect_alerts[0]


def test_alerts_when_withings_requires_reauth(monkeypatch, collect_alerts):
    class ReauthWithingsClient(StubWithingsClient):
        def __init__(self):
            self._state = types.SimpleNamespace(
                requires_reauth=True,
                reason="invalid refresh token",
            )

        def get_summary(self, days_back):
            raise RuntimeError("refresh token revoked")

    monkeypatch.setattr(orchestrator_module, "WithingsClient", ReauthWithingsClient)
    monkeypatch.setattr(
        orchestrator_module.settings,
        "WITHINGS_ALERT_REAUTH",
        True,
        raising=False,
    )

    orch = Orchestrator(dal=StubDal())
    orch.run_daily_sync(days=1)

    assert collect_alerts, "Expected a reauthorisation alert for Withings"
    assert "Withings" in collect_alerts[0]
    assert "reauthor" in collect_alerts[0].lower()


def test_no_reauth_alert_for_rate_limit(monkeypatch, collect_alerts):
    class RateLimitedWithingsClient(StubWithingsClient):
        def get_summary(self, days_back):
            raise RuntimeError("HTTP 429")

    monkeypatch.setattr(orchestrator_module, "WithingsClient", RateLimitedWithingsClient)
    monkeypatch.setattr(
        orchestrator_module.settings,
        "WITHINGS_ALERT_REAUTH",
        True,
        raising=False,
    )

    orch = Orchestrator(dal=StubDal())
    orch.run_daily_sync(days=1)

    assert collect_alerts == [], "Should not send reauth alerts for transient 429s"
