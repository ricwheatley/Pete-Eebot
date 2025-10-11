from __future__ import annotations

from typing import Any

import pytest

from pete_e.infrastructure.telegram_client import TelegramClient


class _DummyResponse:
    def __init__(self, payload: Any | None = None) -> None:
        self._payload = payload or {"ok": True, "result": []}

    def raise_for_status(self) -> None:  # pragma: no cover - behaviour verified via absence of exception
        return None

    def json(self) -> Any:
        return self._payload


def test_send_message_posts_expected_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, *, json: dict[str, Any], timeout: int) -> _DummyResponse:
        calls.append({"url": url, "json": json, "timeout": timeout})
        return _DummyResponse()

    monkeypatch.setattr("pete_e.infrastructure.telegram_client.requests.post", fake_post)

    client = TelegramClient(token="abc123", chat_id="chat-1")
    assert client.send_message("Hello world") is True

    assert calls == [
        {
            "url": "https://api.telegram.org/botabc123/sendMessage",
            "json": {"chat_id": "chat-1", "text": "Hello world"},
            "timeout": 10,
        }
    ]


def test_get_updates_calls_expected_url_and_params(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {}

    def fake_get(url: str, *, params: dict[str, Any], timeout: int) -> _DummyResponse:
        calls.update({"url": url, "params": params, "timeout": timeout})
        payload = {"ok": True, "result": [{"update_id": 1}]}
        return _DummyResponse(payload)

    monkeypatch.setattr("pete_e.infrastructure.telegram_client.requests.get", fake_get)

    client = TelegramClient(token="abc123")
    results = client.get_updates(offset=7, limit=120, timeout=10)

    assert results == [{"update_id": 1}]
    assert calls == {
        "url": "https://api.telegram.org/botabc123/getUpdates",
        "params": {"offset": 7, "limit": 100, "timeout": 10},
        "timeout": 15,
    }
