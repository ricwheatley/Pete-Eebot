from datetime import date, timedelta
import sys
import types
from pathlib import Path

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


if "pete_e.core.plan_builder" not in sys.modules:
    plan_builder_stub = types.ModuleType("pete_e.core.plan_builder")

    class _PlanBuilderStub:
        def __init__(self, *args, **kwargs):  # pragma: no cover - default init
            pass

    plan_builder_stub.PlanBuilder = _PlanBuilderStub
    sys.modules["pete_e.core.plan_builder"] = plan_builder_stub


if "pete_e.core.narrative_builder" not in sys.modules:
    narrative_builder_stub = types.ModuleType("pete_e.core.narrative_builder")

    class _NarrativeBuilderStub:
        def __init__(self, *args, **kwargs):  # pragma: no cover - default init
            pass

        def build_daily_summary(self, data):  # pragma: no cover - basic stub
            return ""

        def build_weekly_plan(self, plan_data, week_number):  # pragma: no cover - basic stub
            return ""

    narrative_builder_stub.NarrativeBuilder = _NarrativeBuilderStub
    sys.modules["pete_e.core.narrative_builder"] = narrative_builder_stub


from pete_e.core import orchestrator as orchestrator_module
from pete_e.core.orchestrator import Orchestrator


class DummyDal:
    def __init__(self):
        self.apple_calls = []

    # Withings -------------------------------------------------------------
    def save_withings_daily(self, day, weight_kg, body_fat_pct):
        pass

    # Apple ----------------------------------------------------------------
    def save_apple_daily(self, day, metrics):
        self.apple_calls.append((day, metrics))

    # Wger -----------------------------------------------------------------
    def save_wger_log(self, day, exercise_id, set_number, reps, weight_kg, rir):
        pass

    def refresh_actual_view(self):
        pass


class DummyWithingsClient:
    def get_summary(self, days_back):
        return None


class DummyWgerClient:
    def get_logs_by_date(self, days):
        return {}


@pytest.fixture(autouse=True)
def stub_clients(monkeypatch):
    monkeypatch.setattr(orchestrator_module, "WithingsClient", DummyWithingsClient)
    monkeypatch.setattr(orchestrator_module, "WgerClient", DummyWgerClient)
    monkeypatch.setattr(Orchestrator, "_recalculate_body_age", lambda self, target_day: None)


def _run_sync_with_payload(monkeypatch, apple_payload):
    dummy_dal = DummyDal()
    orch = Orchestrator(dal=dummy_dal)

    monkeypatch.setattr(
        orchestrator_module.apple_client,
        "get_apple_summary",
        lambda payload: apple_payload,
    )

    orch.run_daily_sync(days=1)
    return dummy_dal


def test_run_daily_sync_skips_empty_apple_payload(monkeypatch):
    target_day = date.today() - timedelta(days=1)
    empty_payload = {
        "date": target_day.isoformat(),
        "steps": None,
        "exercise_minutes": None,
        "calories": {"active": None, "resting": None, "total": None},
        "stand_minutes": None,
        "distance_m": None,
        "heart_rate": {"min": None, "max": None, "avg": None, "resting": None},
        "sleep": {
            "asleep": None,
            "awake": None,
            "core": None,
            "deep": None,
            "rem": None,
            "in_bed": None,
        },
    }

    dummy_dal = _run_sync_with_payload(monkeypatch, empty_payload)

    assert dummy_dal.apple_calls == []


def test_run_daily_sync_persists_when_metrics_present(monkeypatch):
    target_day = date.today() - timedelta(days=1)
    payload_with_steps = {
        "date": target_day.isoformat(),
        "steps": 1234,
        "exercise_minutes": None,
        "calories": {"active": None, "resting": None, "total": None},
        "stand_minutes": None,
        "distance_m": None,
        "heart_rate": {"min": None, "max": None, "avg": None, "resting": None},
        "sleep": {
            "asleep": None,
            "awake": None,
            "core": None,
            "deep": None,
            "rem": None,
            "in_bed": None,
        },
    }

    dummy_dal = _run_sync_with_payload(monkeypatch, payload_with_steps)

    assert len(dummy_dal.apple_calls) == 1
    saved_day, saved_metrics = dummy_dal.apple_calls[0]
    assert saved_day == target_day
    assert saved_metrics["steps"] == 1234
