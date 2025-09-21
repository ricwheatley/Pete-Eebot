import os

import pytest

from pete_e.application import orchestrator as orchestrator_module
from pete_e.application.orchestrator import Orchestrator


class RecordingDal:
    def __init__(self):
        self.withings = []
        self.wger = []

    def save_withings_daily(self, day, weight_kg, body_fat_pct):
        self.withings.append((day, weight_kg, body_fat_pct))

    def save_wger_log(self, day, exercise_id, set_number, reps, weight_kg, rir):
        self.wger.append((day, exercise_id, set_number, reps, weight_kg, rir))

    def refresh_actual_view(self):
        pass


class FlakyWithingsClient:
    def __init__(self):
        self.calls = 0

    def get_summary(self, days_back):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError('withings outage')
        return {'weight': 83.4, 'fat_percent': 19.8}


class ExplodingWgerClient:
    def get_logs_by_date(self, days):
        raise RuntimeError('wger offline')


@pytest.fixture()
def alert_spy(monkeypatch):
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
    return alerts


def test_total_sync_failure_triggers_single_alert(monkeypatch, alert_spy):
    def fail_ingest():
        raise RuntimeError('apple ingest offline')

    monkeypatch.setattr(orchestrator_module, 'run_apple_health_ingest', fail_ingest)
    monkeypatch.setattr(orchestrator_module, 'WithingsClient', FlakyWithingsClient)
    monkeypatch.setattr(orchestrator_module, 'WgerClient', ExplodingWgerClient)

    def fail_body_age(self, target_day):
        raise RuntimeError('body age offline')

    monkeypatch.setattr(Orchestrator, '_recalculate_body_age', fail_body_age)

    dal = RecordingDal()
    orch = Orchestrator(dal=dal)

    success, failures, statuses = orch.run_daily_sync(days=2)

    assert not success
    assert failures == ['AppleDropbox', 'BodyAge', 'Wger', 'Withings']
    assert all(state == 'failed' for state in statuses.values())
    assert len(alert_spy) == 1

    message = alert_spy[0]
    assert isinstance(message, str)

    for secret in (os.environ.get('TELEGRAM_TOKEN'), os.environ.get('TELEGRAM_CHAT_ID')):
        if secret:
            assert secret not in message

