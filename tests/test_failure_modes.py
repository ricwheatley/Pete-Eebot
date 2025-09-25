"""Regression tests for tricky ingest failure modes."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import types
from typing import List

import requests

from pete_e.application import orchestrator as orchestrator_module
from pete_e.application.orchestrator import Orchestrator
from pete_e.infrastructure import withings_client as withings_module
from pete_e.infrastructure.withings_client import WithingsClient


class DummyResponse:
    """Lightweight stand-in for :class:`requests.Response`."""

    def __init__(self, status_code: int, payload: dict | None = None, headers: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def raise_for_status(self) -> None:  # pragma: no cover - behaviour validated via caller
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self) -> dict:
        return self._payload


class RecordingDal:
    """Minimal DAL stub that records persisted entities for assertions."""

    def __init__(self) -> None:
        self.withings_calls: List[tuple] = []
        self.wger_logs: List[tuple] = []

    def save_withings_daily(self, day, weight_kg, body_fat_pct, muscle_pct, water_pct):
        self.withings_calls.append((day, weight_kg, body_fat_pct, muscle_pct, water_pct))

    def save_wger_log(self, day, exercise_id, set_number, reps, weight_kg, rir):  # pragma: no cover - failure path only
        self.wger_logs.append((day, exercise_id, set_number, reps, weight_kg, rir))

    def refresh_actual_view(self):  # pragma: no cover - Wger failure in these tests keeps logs empty
        return None


class MemorySummaryLedger:
    def __init__(self):
        self.sent = {}

    def was_sent(self, target_date):
        return target_date in self.sent

    def mark_sent(self, target_date, summary):
        self.sent[target_date] = summary


def test_withings_client_retries_rate_limits(monkeypatch):
    """A transient 429 should trigger retries before succeeding."""

    client = WithingsClient()
    client.access_token = "token"

    responses = [
        DummyResponse(
            status_code=429,
            payload={"status": 429, "error": "rate limit"},
            headers={"Retry-After": "1"},
        ),
        DummyResponse(
            status_code=429,
            payload={"status": 429, "error": "try later"},
        ),
        DummyResponse(
            status_code=200,
            payload={
                "status": 0,
                "body": {
                    "measuregrps": [
                        {
                            "measures": [
                                {"type": 1, "value": 825, "unit": -1},
                                {"type": 6, "value": 192, "unit": -1},
                                {"type": 76, "value": 417, "unit": -1},
                                {"type": 77, "value": 555, "unit": -1},
                            ]
                        }
                    ]
                },
            },
        ),
    ]

    call_count = {"count": 0}

    def fake_get(url, headers, params, timeout):  # pragma: no cover - exercised via WithingsClient
        idx = call_count["count"]
        call_count["count"] += 1
        return responses[idx]

    sleep_calls: List[float] = []

    def fake_sleep(seconds):  # pragma: no cover - behaviour asserted via recorded calls
        sleep_calls.append(seconds)

    monkeypatch.setattr("pete_e.infrastructure.withings_client.requests.get", fake_get)
    monkeypatch.setattr(withings_module.time, "sleep", fake_sleep)

    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    payload = client._fetch_measures(start, end)

    assert call_count["count"] == 3, "Client should retry until the third attempt succeeds"
    assert sleep_calls == [1, 2], "Backoff should respect Retry-After then exponential growth"
    assert payload["status"] == 0
    assert payload["body"]["measuregrps"][0]["measures"][0]["value"] == 825


def test_run_daily_sync_marks_partial_wger_failure(monkeypatch):
    """Wger errors should not prevent Withings data from being saved."""

    class SuccessfulWithingsClient:
        def __init__(self, *_, **__):
            self.calls: List[int] = []

        def get_summary(self, days_back):
            self.calls.append(days_back)
            return {
                "weight": 82.5,
                "fat_percent": 19.2,
                "muscle_percent": 41.7,
                "water_percent": 55.5,
            }

    class ExplodingWgerClient:
        def __init__(self, *_, **__):
            pass

        def get_logs_by_date(self, days):
            raise RuntimeError("upstream outage")

    def fake_ingest():
        return types.SimpleNamespace(sources=[], workouts=0, daily_points=0)

    monkeypatch.setattr(orchestrator_module, "WithingsClient", SuccessfulWithingsClient)
    monkeypatch.setattr(orchestrator_module, "WgerClient", ExplodingWgerClient)
    monkeypatch.setattr(orchestrator_module, "run_apple_health_ingest", fake_ingest)
    monkeypatch.setattr(Orchestrator, "_recalculate_body_age", lambda self, target_day: None)
    monkeypatch.setattr(orchestrator_module, "DailySummaryDispatchLedger", MemorySummaryLedger)

    dal = RecordingDal()
    orch = Orchestrator(dal=dal)

    success, failures, statuses, undelivered = orch.run_daily_sync(days=1)

    assert not success
    assert failures == ["Wger"]
    assert statuses["Wger"] == "failed"
    assert statuses["Withings"] == "ok"
    assert statuses["AppleDropbox"] == "ok"
    assert statuses["BodyAge"] == "ok"
    assert undelivered == []

    target_day = date.today() - timedelta(days=1)
    assert dal.withings_calls == [(target_day, 82.5, 19.2, 41.7, 55.5)]
    assert dal.wger_logs == []
