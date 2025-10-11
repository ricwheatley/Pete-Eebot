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

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise mocks.requests_mock.HTTPError(response=self)

    def json(self) -> dict:
        return self._payload


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

    sleep_calls: List[float] = []

    def fake_sleep(seconds):
        sleep_calls.append(seconds)

    def fake_post(url, data, timeout):
        return DummyResponse(
            status_code=200,
            payload={"status": 0, "body": {"access_token": "abc", "refresh_token": "def"}},
        )

    monkeypatch.setattr("pete_e.infrastructure.withings_client.requests.get", fake_get)
    monkeypatch.setattr("pete_e.infrastructure.withings_client.requests.post", fake_post)
    monkeypatch.setattr(withings_module.time, "sleep", fake_sleep)

    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    payload = client._fetch_measures(start, end)

    assert call_count["count"] == 3
    assert sleep_calls == [1, 2]
    assert payload["status"] == 0
