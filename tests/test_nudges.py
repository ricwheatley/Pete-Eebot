import sys
import types
from datetime import date, timedelta
from pathlib import Path

import pytest


if "pete_e.config" not in sys.modules:
    config_stub = types.ModuleType("pete_e.config")

    class _SettingsStub:
        USER_DATE_OF_BIRTH = date(1990, 1, 1)
        DATABASE_URL = "postgresql://stub"
        NUDGE_WITHINGS_STALE_DAYS = 3
        NUDGE_STRAIN_THRESHOLD = 185.0
        NUDGE_STRAIN_CONSECUTIVE_DAYS = 3

        def __getattr__(self, name):  # pragma: no cover - defensive default
            return None

        @property
        def log_path(self):  # pragma: no cover - ensure log path is writable
            return Path("logs/test.log")

    config_stub.settings = _SettingsStub()
    sys.modules["pete_e.config"] = config_stub

    config_config_stub = types.ModuleType("pete_e.config.config")
    config_config_stub.Settings = object
    config_config_stub.settings = config_stub.settings
    sys.modules["pete_e.config.config"] = config_config_stub


if "pete_e.infrastructure.postgres_dal" not in sys.modules:
    postgres_stub = types.ModuleType("pete_e.infrastructure.postgres_dal")

    class _PostgresStub:
        def __init__(self, *args, **kwargs):  # pragma: no cover - guardrail
            raise RuntimeError("Database access should be stubbed in tests")

    postgres_stub.PostgresDal = _PostgresStub
    postgres_stub.close_pool = lambda: None
    sys.modules["pete_e.infrastructure.postgres_dal"] = postgres_stub


from pete_e.application.orchestrator import Orchestrator
from pete_e.domain import narrative_builder


class StubDal:
    def __init__(self, *, history=None, lift_log=None):
        self.history = history or []
        self.lift_log = lift_log or {}
        self.history_requests = []
        self.lift_requests = []

    def get_historical_metrics(self, days: int):
        self.history_requests.append(days)
        if not self.history:
            return []
        window = min(days, len(self.history))
        return list(self.history[-window:])

    def load_lift_log(self, exercise_ids=None, start_date=None, end_date=None):
        self.lift_requests.append({
            "exercise_ids": exercise_ids,
            "start_date": start_date,
            "end_date": end_date,
        })
        if not self.lift_log:
            return {}
        if end_date is None:
            return self.lift_log
        filtered = {}
        for key, entries in self.lift_log.items():
            bucket = []
            for entry in entries:
                entry_date = entry.get("date")
                if entry_date is None or entry_date <= end_date:
                    bucket.append(entry)
            if bucket:
                filtered[key] = bucket
        return filtered


@pytest.fixture
def capture_nudges(monkeypatch):
    messages = []
    calls = []

    def fake_send(self, message):
        messages.append(message)
        return True

    def fake_voice(tag, sprinkles=None):
        calls.append({"tag": tag, "sprinkles": list(sprinkles or [])})
        detail = " | ".join(sprinkles or [])
        return f"{tag}:{detail}" if detail else tag

    monkeypatch.setattr(Orchestrator, "send_telegram_message", fake_send, raising=False)
    monkeypatch.setattr(narrative_builder.PeteVoice, "nudge", fake_voice, raising=False)
    return {"messages": messages, "calls": calls}


def _day(base: date, offset: int, **overrides):
    record = {
        "date": base + timedelta(days=offset),
        "weight_kg": overrides.get("weight_kg"),
        "calories_active": overrides.get("calories_active", 0),
        "exercise_minutes": overrides.get("exercise_minutes", 0),
        "strength_volume_kg": overrides.get("strength_volume_kg", 0),
    }
    record.update(overrides)
    return record


def test_withings_stale_triggers_single_nudge(capture_nudges):
    reference = date(2025, 1, 10)
    history = [
        _day(reference, -4, weight_kg=81.6, exercise_minutes=30, calories_active=280),
        _day(reference, -3, weight_kg=81.4, exercise_minutes=28, calories_active=260),
        _day(reference, -2, weight_kg=None, exercise_minutes=20),
        _day(reference, -1, weight_kg=None, exercise_minutes=15),
        _day(reference, 0, weight_kg=None, exercise_minutes=10),
    ]
    dal = StubDal(history=history)
    orch = Orchestrator(dal=dal)

    dispatched = orch.dispatch_nudges(reference_date=reference)

    assert dispatched == capture_nudges["messages"]
    assert len(dispatched) == 1
    assert capture_nudges["calls"][0]["tag"] == "#WithingsCheck"
    sprinkle = " ".join(capture_nudges["calls"][0]["sprinkles"]).lower()
    assert "withings" in sprinkle
    assert "day" in sprinkle


def test_high_strain_rest_nudge(capture_nudges):
    reference = date(2025, 3, 4)
    history = [
        _day(reference, -3, weight_kg=82.0, exercise_minutes=40, calories_active=400, strength_volume_kg=2500),
        _day(reference, -2, weight_kg=82.1, exercise_minutes=95, calories_active=880, strength_volume_kg=13800),
        _day(reference, -1, weight_kg=82.2, exercise_minutes=96, calories_active=910, strength_volume_kg=14200),
        _day(reference, 0, weight_kg=82.3, exercise_minutes=92, calories_active=905, strength_volume_kg=13950),
    ]
    dal = StubDal(history=history)
    orch = Orchestrator(dal=dal)

    dispatched = orch.dispatch_nudges(reference_date=reference)

    assert dispatched == capture_nudges["messages"]
    assert len(dispatched) == 1
    assert capture_nudges["calls"][0]["tag"] == "#HighStrainRest"
    sprinkle = " ".join(capture_nudges["calls"][0]["sprinkles"]).lower()
    assert "strain" in sprinkle
    assert "recovery" in sprinkle


def test_personal_best_nudge_lists_new_records(capture_nudges):
    reference = date(2025, 4, 1)
    history = [
        _day(reference, -1, weight_kg=81.0, exercise_minutes=45, calories_active=420, strength_volume_kg=5200),
        _day(reference, 0, weight_kg=81.1, exercise_minutes=50, calories_active=440, strength_volume_kg=5400),
    ]
    lift_log = {
        "101": [
            {"date": reference - timedelta(days=14), "weight_kg": 95.0, "reps": 5, "set_number": 1},
            {"date": reference, "weight_kg": 100.0, "reps": 5, "set_number": 1},
        ],
        "202": [
            {"date": reference - timedelta(days=30), "weight_kg": 60.0, "reps": 8, "set_number": 1},
            {"date": reference, "weight_kg": 62.5, "reps": 8, "set_number": 1},
        ],
    }
    dal = StubDal(history=history, lift_log=lift_log)
    orch = Orchestrator(dal=dal)

    dispatched = orch.dispatch_nudges(reference_date=reference)

    assert dispatched == capture_nudges["messages"]
    assert len(dispatched) == 1
    call = capture_nudges["calls"][0]
    assert call["tag"] == "#PersonalBest"
    summary_text = " ".join(call["sprinkles"])
    assert "101" in summary_text and "202" in summary_text
    assert "pb" in summary_text.lower() or "personal best" in summary_text.lower()

