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


def test_ping_calls_get_me_and_reports_configured_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {}

    def fake_get(url: str, *, timeout: float) -> _DummyResponse:
        calls.update({"url": url, "timeout": timeout})
        payload = {"ok": True, "result": {"username": "peteeebot"}}
        return _DummyResponse(payload)

    monkeypatch.setattr("pete_e.infrastructure.telegram_client.requests.get", fake_get)

    client = TelegramClient(token="abc123", chat_id="chat-1", request_timeout=2.5)
    detail = client.ping()

    assert detail == "@peteeebot chat configured"
    assert calls == {
        "url": "https://api.telegram.org/botabc123/getMe",
        "timeout": 2.5,
    }


def test_ping_requires_chat_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pete_e.infrastructure.telegram_client.settings.TELEGRAM_CHAT_ID", "")
    client = TelegramClient(token="abc123")

    with pytest.raises(RuntimeError) as exc:
        client.ping()

    assert "chat_id missing" in str(exc.value)
