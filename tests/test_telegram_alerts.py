from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import requests

from pete_e.infrastructure import wger_client as wger_client_module
from pete_e.infrastructure.wger_client import WgerClient, WgerError


class _FakeResponse:
    def __init__(self, status: int, payload: dict | None = None) -> None:
        self.status_code = status
        self._payload = payload or {}
        self.text = json.dumps(self._payload)

    def json(self) -> dict:
        return self._payload


def _response(status: int, payload: dict | None = None) -> _FakeResponse:
    return _FakeResponse(status, payload)


def _configured_client() -> WgerClient:
    client = WgerClient()
    client.base_url = "https://wger.de"
    client.timeout = 5
    client.debug_api = False
    client.max_retries = 3
    client.backoff_base = 0
    return client


def test_wger_client_retry_logic() -> None:
    client = WgerClient()
    retryable = [408, 429, 500, 502, 503, 504]
    assert all(client._should_retry(code) for code in retryable)  # type: ignore[attr-defined]
    assert client._should_retry(404) is False  # type: ignore[attr-defined]


def test_wger_client_request_retries_and_succeeds(monkeypatch):
    # --- Arrange ---
    monkeypatch.setattr("pete_e.infrastructure.wger_client.settings", SimpleNamespace(
        WGER_BASE_URL="https://wger.de/api/v2",
        WGER_API_KEY="dummy-key",
        WGER_USERNAME="user",
        WGER_PASSWORD="pass",
    ))

    # Mock the JWT fetch to avoid network calls
    monkeypatch.setattr("pete_e.infrastructure.wger_client.WgerClient._get_jwt_token", lambda self: "jwt123")

    attempts = []
    responses = [
        requests.RequestException("boom"),
        requests.RequestException("slow"),
        _response(200, {"ok": True}),
    ]

    def fake_request(*args, **kwargs):
        attempt = len(attempts)
        attempts.append(attempt)
        result = responses[attempt]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(wger_client_module.requests, "request", fake_request, raising=False)
    monkeypatch.setattr("pete_e.infrastructure.decorators.time.sleep", lambda _: None)

    # --- Act ---
    client = _configured_client()
    result = client._request("GET", "/test/")

    # --- Assert ---
    assert result == {"ok": True}
    assert len(attempts) == 3



def test_wger_client_request_raises_after_non_retryable(monkeypatch):
    monkeypatch.setattr("pete_e.infrastructure.wger_client.settings", SimpleNamespace(
        WGER_BASE_URL="https://wger.de/api/v2",
        WGER_API_KEY="dummy-key",
        WGER_USERNAME="user",
        WGER_PASSWORD="pass",
    ))
    monkeypatch.setattr("pete_e.infrastructure.wger_client.WgerClient._get_jwt_token", lambda self: "jwt123")
    monkeypatch.setattr("pete_e.infrastructure.decorators.time.sleep", lambda _: None)

    def fake_request(*args, **kwargs):
        return _response(404, {"detail": "not found"})

    monkeypatch.setattr(wger_client_module.requests, "request", fake_request, raising=False)

    client = _configured_client()
    with pytest.raises(WgerError) as e:
        client._request("GET", "/missing/")
    assert "404" in str(e.value)

