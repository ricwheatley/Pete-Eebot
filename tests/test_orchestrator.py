from datetime import date, timedelta
import sys
import types
from pathlib import Path
import os

import pytest


if "pete_e.config" not in sys.modules:
    config_stub = types.ModuleType("pete_e.config")

    class _SettingsStub:
        USER_DATE_OF_BIRTH = date(1990, 1, 1)
        DATABASE_URL = "postgresql://stub"

        def __getattr__(self, name):  # pragma: no cover - defensive default
            return None

        @property
        def log_path(self):  # pragma: no cover - ensure log path is writable
            return Path("logs/test.log")

    config_stub.settings = _SettingsStub()
    sys.modules["pete_e.config"] = config_stub

if "pete_e.data_access.postgres_dal" not in sys.modules:
    postgres_stub = types.ModuleType("pete_e.data_access.postgres_dal")

    class _PostgresDalStub:
        def __init__(self, *args, **kwargs):  # pragma: no cover - default init
            pass

    postgres_stub.PostgresDal = _PostgresDalStub
    postgres_stub.close_pool = lambda: None
    sys.modules["pete_e.data_access.postgres_dal"] = postgres_stub
from pete_e.application import orchestrator as orchestrator_module
from pete_e.application.orchestrator import Orchestrator


class DummyDal:
    def __init__(self):
        self.apple_calls = []
        self.withings_calls = []
        self.wger_logs = []
        self.refreshed = False

    # Withings -------------------------------------------------------------
    def save_withings_daily(self, day, weight_kg, body_fat_pct):
        self.withings_calls.append((day, weight_kg, body_fat_pct))

    # Apple ----------------------------------------------------------------
    def save_apple_daily(self, day, metrics):  # pragma: no cover - legacy compatibility
        self.apple_calls.append((day, metrics))

    # Wger -----------------------------------------------------------------
    def save_wger_log(self, day, exercise_id, set_number, reps, weight_kg, rir):
        self.wger_logs.append((day, exercise_id, set_number, reps, weight_kg, rir))

    def refresh_actual_view(self):
        self.refreshed = True


class DummyWithingsClient:
    next_summary = None

    def get_summary(self, days_back):
        return self.next_summary


class DummyWgerClient:
    next_logs = {}

    def get_logs_by_date(self, days):
        return self.next_logs


@pytest.fixture(autouse=True)
def stub_clients(monkeypatch):
    DummyWithingsClient.next_summary = None
    DummyWgerClient.next_logs = {}
    monkeypatch.setattr(orchestrator_module, "WithingsClient", DummyWithingsClient)
    monkeypatch.setattr(orchestrator_module, "WgerClient", DummyWgerClient)
    monkeypatch.setattr(Orchestrator, "_recalculate_body_age", lambda self, target_day: None)
    monkeypatch.setattr(
        orchestrator_module,
        "run_apple_health_ingest",
        lambda: types.SimpleNamespace(sources=[], workouts=0, daily_points=0),
    )


def test_run_daily_sync_handles_absent_apple_data():
    dummy_dal = DummyDal()
    orch = Orchestrator(dal=dummy_dal)

    success, failures, statuses = orch.run_daily_sync(days=1)

    assert success
    assert failures == []
    assert statuses['AppleDropbox'] == 'ok'
    assert statuses['Withings'] == 'ok'
    assert statuses['Wger'] == 'ok'
    assert statuses['BodyAge'] == 'ok'
    assert dummy_dal.apple_calls == []


def test_run_daily_sync_persists_withings_and_wger(monkeypatch):
    target_day = date.today() - timedelta(days=1)
    DummyWithingsClient.next_summary = {"weight": 82.5, "fat_percent": 19.2}
    DummyWgerClient.next_logs = {
        target_day.isoformat(): [
            {"exercise_id": 7, "reps": 10, "weight": 45.0, "rir": 2},
            {"exercise_id": 7, "reps": 8, "weight": 47.5, "rir": 1},
        ]
    }

    dummy_dal = DummyDal()
    orch = Orchestrator(dal=dummy_dal)

    success, failures, statuses = orch.run_daily_sync(days=1)

    assert success
    assert failures == []
    assert statuses['AppleDropbox'] == 'ok'
    assert statuses['Withings'] == 'ok'
    assert statuses['Wger'] == 'ok'
    assert statuses['BodyAge'] == 'ok'
    assert dummy_dal.withings_calls == [(target_day, 82.5, 19.2)]
    assert dummy_dal.wger_logs == [
        (target_day, 7, 1, 10, 45.0, 2),
        (target_day, 7, 2, 8, 47.5, 1),
    ]
    assert dummy_dal.refreshed is True

def test_run_daily_sync_alerts_on_ingest_failure(monkeypatch):
    alerts = []

    def fake_alert(message):
        alerts.append(message)
        return True

    monkeypatch.setattr(
        orchestrator_module.telegram_sender,
        'send_alert',
        fake_alert,
        raising=False,
    )

    def fail_ingest():
        raise RuntimeError('apple ingest exploded')

    monkeypatch.setattr(orchestrator_module, 'run_apple_health_ingest', fail_ingest)

    dummy_dal = DummyDal()
    orch = Orchestrator(dal=dummy_dal)

    success, failures, statuses = orch.run_daily_sync(days=1)

    assert not success
    assert statuses['AppleDropbox'] == 'failed'
    assert 'AppleDropbox' in failures
    assert len(alerts) == 1
    assert isinstance(alerts[0], str)

    token = os.environ.get('TELEGRAM_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    for secret in (token, chat_id):
        if secret:
            assert secret not in alerts[0]

