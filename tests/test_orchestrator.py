from datetime import date, timedelta
import sys
import types
from pathlib import Path
import os

import pytest

from tests import config_stub, rich_stub  # noqa: F401 - ensure dependencies are stubbed
from tests.mock_dal import MockableDal

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
from pete_e.cli import messenger as messenger_module


class DummyDal(MockableDal):
    def __init__(self):
        self.withings_calls = []
        self.wger_logs = []
        self.refreshed = False

    # Withings -------------------------------------------------------------
    def save_withings_daily(self, day, weight_kg, body_fat_pct, muscle_pct, water_pct):
        self.withings_calls.append((day, weight_kg, body_fat_pct, muscle_pct, water_pct))

    # Wger -----------------------------------------------------------------
    def save_wger_log(self, day, exercise_id, set_number, reps, weight_kg, rir):
        self.wger_logs.append((day, exercise_id, set_number, reps, weight_kg, rir))

    def refresh_actual_view(self):
        self.refreshed = True

    def refresh_daily_summary(self, days: int = 7) -> None:
        self.refreshed = True

    def has_any_plan(self) -> bool:
        return True


class DummyWithingsClient:
    next_summary = None

    def get_summary(self, days_back):
        return self.next_summary


class DummyWgerClient:
    next_logs = {}

    def get_logs_by_date(self, days):
        return self.next_logs


class MemorySummaryLedger:
    def __init__(self):
        self.sent = {}

    def was_sent(self, target_date):
        return target_date in self.sent

    def mark_sent(self, target_date, summary):
        self.sent[target_date] = summary


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
    monkeypatch.setattr(
        orchestrator_module,
        "DailySummaryDispatchLedger",
        MemorySummaryLedger,
    )


@pytest.fixture(autouse=True)
def summary_spy(monkeypatch):
    calls = []

    def fake_send_daily_summary(*, orchestrator, target_date=None):
        calls.append({"orchestrator": orchestrator, "target_date": target_date})
        return "stub-summary"

    monkeypatch.setattr(
        messenger_module,
        "send_daily_summary",
        fake_send_daily_summary,
        raising=False,
    )
    return calls


def test_run_daily_sync_handles_absent_apple_data():
    dummy_dal = DummyDal()
    orch = Orchestrator(dal=dummy_dal)

    success, failures, statuses, undelivered = orch.run_daily_sync(days=1)

    assert success
    assert failures == []
    assert statuses["AppleDropbox"] == "ok"
    assert statuses["Withings"] == "ok"
    assert statuses["Wger"] == "ok"
    assert statuses["BodyAge"] == "ok"
    assert undelivered == []


def test_run_daily_sync_persists_withings_and_wger(monkeypatch):
    target_day = date.today() - timedelta(days=1)
    DummyWithingsClient.next_summary = {"weight": 82.5, "fat_percent": 19.2, "muscle_percent": 41.7, "water_percent": 55.5}
    DummyWgerClient.next_logs = {
        target_day.isoformat(): [
            {"exercise_id": 7, "reps": 10, "weight": 45.0, "rir": 2},
            {"exercise_id": 7, "reps": 8, "weight": 47.5, "rir": 1},
        ]
    }

    dummy_dal = DummyDal()
    orch = Orchestrator(dal=dummy_dal)

    success, failures, statuses, undelivered = orch.run_daily_sync(days=1)

    assert success
    assert failures == []
    assert statuses["AppleDropbox"] == "ok"
    assert statuses["Withings"] == "ok"
    assert statuses["Wger"] == "ok"
    assert statuses["BodyAge"] == "ok"
    assert dummy_dal.withings_calls == [(target_day, 82.5, 19.2, 41.7, 55.5)]
    assert dummy_dal.wger_logs == [
        (target_day, 7, 1, 10, 45.0, 2),
        (target_day, 7, 2, 8, 47.5, 1),
    ]
    assert dummy_dal.refreshed is True
    assert undelivered == []


def test_run_daily_sync_alerts_on_ingest_failure(monkeypatch, summary_spy):
    alerts = []

    def fake_alert(message):
        alerts.append(message)
        return True

    monkeypatch.setattr(
        orchestrator_module.telegram_sender,
        "send_alert",
        fake_alert,
        raising=False,
    )

    def fail_ingest():
        raise RuntimeError("apple ingest exploded")

    monkeypatch.setattr(orchestrator_module, "run_apple_health_ingest", fail_ingest)

    dummy_dal = DummyDal()
    ledger = MemorySummaryLedger()
    orch = Orchestrator(dal=dummy_dal, summary_dispatch_ledger=ledger)

    success, failures, statuses, undelivered = orch.run_daily_sync(days=1)

    assert not success
    assert statuses["AppleDropbox"] == "failed"
    assert "AppleDropbox" in failures
    assert len(alerts) == 1
    assert isinstance(alerts[0], str)
    assert len(summary_spy) == 0
    assert ledger.sent == {}
    assert undelivered == []

    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    for secret in (token, chat_id):
        if secret:
            assert secret not in alerts[0]


def test_run_daily_sync_sends_summary_after_success(summary_spy):
    dummy_dal = DummyDal()
    ledger = MemorySummaryLedger()
    orch = Orchestrator(dal=dummy_dal, summary_dispatch_ledger=ledger)

    success, failures, statuses, undelivered = orch.run_daily_sync(days=1)

    assert success
    assert failures == []
    target = date.today() - timedelta(days=1)
    assert len(summary_spy) == 1
    assert summary_spy[0]["target_date"] == target
    assert ledger.was_sent(target)
    assert undelivered == []


def test_run_daily_sync_summary_idempotent(summary_spy):
    dummy_dal = DummyDal()
    ledger = MemorySummaryLedger()
    orch = Orchestrator(dal=dummy_dal, summary_dispatch_ledger=ledger)

    success1, _, _, _ = orch.run_daily_sync(days=1)
    success2, _, _, _ = orch.run_daily_sync(days=1)

    assert success1
    assert success2
    assert len(summary_spy) == 1


def test_run_daily_sync_returns_pending_alerts_when_telegram_disabled(monkeypatch, summary_spy):
    alerts = []

    def fake_alert(message):
        alerts.append(message)
        return False

    monkeypatch.setattr(
        orchestrator_module.telegram_sender,
        "send_alert",
        fake_alert,
        raising=False,
    )

    log_calls = []

    def record_log(message, level="INFO"):
        log_calls.append((message, level))

    monkeypatch.setattr(
        orchestrator_module.log_utils,
        "log_message",
        record_log,
    )

    def fail_ingest():
        raise RuntimeError("apple ingest exploded")

    monkeypatch.setattr(orchestrator_module, "run_apple_health_ingest", fail_ingest)

    dummy_dal = DummyDal()
    ledger = MemorySummaryLedger()
    orch = Orchestrator(dal=dummy_dal, summary_dispatch_ledger=ledger)

    success, failures, statuses, undelivered = orch.run_daily_sync(days=1)

    assert not success
    assert statuses["AppleDropbox"] == "failed"
    assert "AppleDropbox" in failures
    assert alerts and len(alerts) == 1
    assert undelivered == alerts
    assert any("Telegram alert dispatch unavailable" in msg for msg, _ in log_calls)
    assert ledger.sent == {}
    assert len(summary_spy) == 0
