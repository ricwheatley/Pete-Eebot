"""Regression tests for tricky network behaviours."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import mocks.requests_mock

from unittest.mock import Mock

from pete_e.domain.token_storage import TokenStorage
from pete_e.infrastructure import withings_client as withings_module
from pete_e.infrastructure.withings_client import WithingsClient


class DummyResponse:
    def __init__(self, status_code: int, payload: dict | None = None, headers: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}
        """Initialize this object."""

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise mocks.requests_mock.HTTPError(response=self)
        """Perform raise for status."""

    def json(self) -> dict:
        return self._payload
        """Perform json."""
    """Represent DummyResponse."""


def test_withings_client_retries_rate_limits(monkeypatch):
    token_storage = Mock(spec=TokenStorage)
    token_storage.read_tokens.return_value = {
        "access_token": "token",
        "refresh_token": "refresh",
        "expires_at": int((datetime.now(timezone.utc) + timedelta(hours=2)).timestamp()),
    }

    client = WithingsClient(token_storage=token_storage)

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

    def fake_get(url, headers, params, timeout):
        idx = call_count["count"]
        call_count["count"] += 1
        return responses[idx]
        """Perform fake get."""

    sleep_calls: List[float] = []

    def fake_sleep(seconds):
        sleep_calls.append(seconds)
        """Perform fake sleep."""

    def fake_post(url, data, timeout):
        return DummyResponse(
            status_code=200,
            payload={"status": 0, "body": {"access_token": "abc", "refresh_token": "def"}},
        )
        """Perform fake post."""

    monkeypatch.setattr("pete_e.infrastructure.withings_client.requests.get", fake_get)
    monkeypatch.setattr("pete_e.infrastructure.withings_client.requests.post", fake_post)
    monkeypatch.setattr(withings_module.time, "sleep", fake_sleep)

    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    payload = client._fetch_measures(start, end)

    assert call_count["count"] == 3
    assert sleep_calls == [1, 2]
    assert payload["status"] == 0
    """Perform test withings client retries rate limits."""


def test_withings_client_reloads_tokens_when_storage_changes(monkeypatch):
    future_expiry = int((datetime.now(timezone.utc) + timedelta(hours=2)).timestamp())

    token_storage = Mock(spec=TokenStorage)
    token_storage.read_tokens.side_effect = [
        {"access_token": "first", "refresh_token": "r1", "expires_at": future_expiry},
        {"access_token": "second", "refresh_token": "r2", "expires_at": future_expiry},
    ]

    client = WithingsClient(token_storage=token_storage)

    monkeypatch.setattr(
        client,
        "_refresh_access_token",
        Mock(side_effect=AssertionError("should not refresh when tokens are valid")),
    )

    client.ensure_fresh_token()

    assert client.access_token == "second"
    assert client.refresh_token == "r2"
    assert client._cached_tokens["access_token"] == "second"
    assert token_storage.read_tokens.call_count == 2
    """Perform test withings client reloads tokens when storage changes."""


def test_withings_summary_collects_all_measure_groups_and_derives_water_percent(monkeypatch):
    future_expiry = int((datetime.now(timezone.utc) + timedelta(hours=2)).timestamp())

    token_storage = Mock(spec=TokenStorage)
    token_storage.read_tokens.return_value = {
        "access_token": "token",
        "refresh_token": "refresh",
        "expires_at": future_expiry,
    }

    client = WithingsClient(token_storage=token_storage)
    monkeypatch.setattr(
        client,
        "_fetch_measures",
        lambda start, end: {
            "status": 0,
            "body": {
                "measuregrps": [
                    {
                        "grpid": 7614618996,
                        "date": 1776051256,
                        "created": 1776051318,
                        "modified": 1776051318,
                        "model": "Body Comp",
                        "modelid": 18,
                        "timezone": "Europe/London",
                        "measures": [
                            {"type": 167, "value": 51674, "unit": -3},
                        ],
                    },
                    {
                        "grpid": 7614618991,
                        "date": 1776051256,
                        "created": 1776051318,
                        "modified": 1776051318,
                        "model": "Body Comp",
                        "modelid": 18,
                        "timezone": "Europe/London",
                        "measures": [
                            {"type": 1, "value": 92891, "unit": -3},
                            {"type": 5, "value": 6707, "unit": -2},
                            {"type": 6, "value": 27785, "unit": -3},
                            {"type": 8, "value": 2581, "unit": -2},
                            {"type": 76, "value": 6374, "unit": -2},
                            {"type": 77, "value": 4735, "unit": -2},
                            {"type": 88, "value": 333, "unit": -2},
                            {"type": 170, "value": 48, "unit": -1},
                            {"type": 226, "value": 1963, "unit": 0},
                            {"type": 227, "value": 47, "unit": 0},
                        ],
                    },
                ],
            },
        },
    )

    summary = client.get_summary(days_back=0)

    assert summary["weight"] == 92.89
    assert summary["fat_percent"] == 27.79
    assert summary["fat_free_mass_kg"] == 67.07
    assert summary["fat_mass_kg"] == 25.81
    assert summary["muscle_mass_kg"] == 63.74
    assert summary["bone_mass_kg"] == 3.33
    assert summary["visceral_fat_index"] == 4.8
    assert summary["bmr_kcal_day"] == 1963.0
    assert summary["metabolic_age_years"] == 47.0
    assert summary["nerve_health_score_feet"] == 51.674
    assert summary["water_percent"] == 50.97
    assert summary["measure_type_values"]["227"] == 47.0
    assert len(summary["measure_groups"]) == 2
    """Perform test withings summary collects all measure groups and derives water percent."""
