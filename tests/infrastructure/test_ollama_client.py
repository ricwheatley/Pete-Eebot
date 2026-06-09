from __future__ import annotations

import pytest
import requests

from pete_e.infrastructure.ollama_client import OllamaChatClient, OllamaClientError


class _Response:
    def __init__(
        self,
        payload=None,
        *,
        status_code: int = 200,
        http_error: Exception | None = None,
        json_error: Exception | None = None,
    ) -> None:
        self.payload = payload
        self.status_code = status_code
        self.http_error = http_error
        self.json_error = json_error

    def raise_for_status(self) -> None:
        if self.http_error is not None:
            raise self.http_error
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if self.json_error is not None:
            raise self.json_error
        return self.payload


class _Http:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[dict] = []

    def post(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.response


def test_ollama_client_posts_chat_payload_and_returns_content() -> None:
    http = _Http(_Response({"message": {"content": " rewritten \n"}}))
    client = OllamaChatClient(
        base_url="http://127.0.0.1:11434/",
        model="gemma3",
        timeout_seconds=20.0,
        http_client=http,
    )

    result = client.chat([{"role": "user", "content": "draft"}])

    assert result == "rewritten"
    assert http.calls[0]["url"] == "http://127.0.0.1:11434/api/chat"
    assert http.calls[0]["timeout"] == 20.0
    payload = http.calls[0]["json"]
    assert payload["model"] == "gemma3"
    assert payload["stream"] is False
    assert payload["messages"] == [{"role": "user", "content": "draft"}]
    assert payload["options"]["temperature"] <= 0.2


def test_ollama_client_ping_uses_configured_model() -> None:
    http = _Http(_Response({"message": {"content": "ok"}}))
    client = OllamaChatClient(
        base_url="http://127.0.0.1:11434",
        model="gemma3",
        timeout_seconds=2.5,
        http_client=http,
    )

    assert client.ping() == "gemma3 reachable"
    assert http.calls[0]["json"]["model"] == "gemma3"
    assert http.calls[0]["json"]["messages"][1]["content"] == "health check"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"message": None},
        {"message": {}},
        {"message": {"content": "   "}},
    ],
)
def test_ollama_client_rejects_bad_response_shape(payload) -> None:
    client = OllamaChatClient(
        base_url="http://127.0.0.1:11434",
        model="gemma3",
        timeout_seconds=20.0,
        http_client=_Http(_Response(payload)),
    )

    with pytest.raises(OllamaClientError):
        client.chat([{"role": "user", "content": "draft"}])


def test_ollama_client_wraps_http_failure() -> None:
    client = OllamaChatClient(
        base_url="http://127.0.0.1:11434",
        model="gemma3",
        timeout_seconds=20.0,
        http_client=_Http(_Response(http_error=requests.exceptions.HTTPError("HTTP 500"))),
    )

    with pytest.raises(OllamaClientError, match="Ollama chat request failed"):
        client.chat([{"role": "user", "content": "draft"}])


def test_ollama_client_rejects_invalid_json() -> None:
    client = OllamaChatClient(
        base_url="http://127.0.0.1:11434",
        model="gemma3",
        timeout_seconds=20.0,
        http_client=_Http(_Response(json_error=ValueError("bad json"))),
    )

    with pytest.raises(OllamaClientError, match="invalid JSON"):
        client.chat([{"role": "user", "content": "draft"}])
