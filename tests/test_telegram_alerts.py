from __future__ import annotations

import json
from typing import List

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


def test_wger_client_retry_logic() -> None:
    client = WgerClient()
    retryable = [408, 429, 500, 502, 503, 504]
    assert all(client._should_retry(code) for code in retryable)  # type: ignore[attr-defined]
    assert client._should_retry(404) is False  # type: ignore[attr-defined]


def test_wger_client_request_retries_and_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: List[int] = []

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

    client = WgerClient()
    assert client._request("GET", "/test/") == {"ok": True}
    assert len(attempts) == 3


def test_wger_client_request_raises_after_non_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pete_e.infrastructure.decorators.time.sleep", lambda _: None)

    def fake_request(*args, **kwargs):
        return _response(404, {"detail": "not found"})

    monkeypatch.setattr(wger_client_module.requests, "request", fake_request, raising=False)

    client = WgerClient()
    with pytest.raises(WgerError):
        client._request("GET", "/missing/")
