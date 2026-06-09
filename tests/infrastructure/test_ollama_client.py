from __future__ import annotations

import pytest
import requests

from pete_e.infrastructure.ollama_client import (
    OllamaChatClient,
    OllamaClientError,
    OllamaHealthCheckError,
    OllamaModelMissingError,
)


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
    def __init__(self, response: _Response | None = None, *, get_response: _Response | None = None) -> None:
        self.response = response or _Response()
        self.get_response = get_response or _Response()
        self.calls: list[dict] = []

    def post(self, url: str, **kwargs):
        self.calls.append({"method": "POST", "url": url, **kwargs})
        return self.response

    def get(self, url: str, **kwargs):
        self.calls.append({"method": "GET", "url": url, **kwargs})
        return self.get_response


def test_ollama_client_posts_chat_payload_and_returns_content() -> None:
    http = _Http(_Response({"message": {"content": " rewritten \n"}}))
    client = OllamaChatClient(
        base_url="http://127.0.0.1:11434/",
        model="qwen2.5:1.5b",
        timeout_seconds=30.0,
        http_client=http,
    )

    result = client.chat([{"role": "user", "content": "draft"}])

    assert result == "rewritten"
    assert http.calls[0]["url"] == "http://127.0.0.1:11434/api/chat"
    assert http.calls[0]["timeout"] == 30.0
    payload = http.calls[0]["json"]
    assert payload["model"] == "qwen2.5:1.5b"
    assert payload["stream"] is False
    assert payload["messages"] == [{"role": "user", "content": "draft"}]
    assert payload["options"]["temperature"] == 0.4
    assert payload["options"]["num_predict"] == 220


def test_ollama_client_chat_options_can_be_overridden() -> None:
    http = _Http(_Response({"message": {"content": "custom"}}))
    client = OllamaChatClient(
        base_url="http://127.0.0.1:11434",
        model="qwen2.5:1.5b",
        timeout_seconds=30.0,
        http_client=http,
        options={"temperature": 0.1, "num_predict": 42},
    )

    assert client.chat([{"role": "user", "content": "draft"}]) == "custom"
    assert http.calls[0]["json"]["options"] == {"temperature": 0.1, "num_predict": 42}


def test_ollama_client_ping_uses_tags_then_tiny_chat() -> None:
    http = _Http(
        _Response({"message": {"content": "ok"}}),
        get_response=_Response({"models": [{"name": "qwen2.5:1.5b"}]}),
    )
    client = OllamaChatClient(
        base_url="http://127.0.0.1:11434",
        model="qwen2.5:1.5b",
        timeout_seconds=2.5,
        http_client=http,
    )

    assert client.ping() == "qwen2.5:1.5b OK"
    assert http.calls[0]["method"] == "GET"
    assert http.calls[0]["url"] == "http://127.0.0.1:11434/api/tags"
    assert http.calls[1]["method"] == "POST"
    assert http.calls[1]["json"]["model"] == "qwen2.5:1.5b"
    assert http.calls[1]["json"]["messages"][1]["content"] == "OK?"
    assert http.calls[1]["json"]["options"]["num_predict"] <= 16


def test_ollama_client_ping_reports_missing_model_clearly() -> None:
    client = OllamaChatClient(
        base_url="http://127.0.0.1:11434",
        model="qwen2.5:1.5b",
        timeout_seconds=2.5,
        http_client=_Http(get_response=_Response({"models": [{"name": "llama3.2"}]})),
    )

    with pytest.raises(OllamaModelMissingError, match="configured model missing: qwen2.5:1.5b"):
        client.ping()


def test_ollama_client_ping_reports_tiny_chat_failure() -> None:
    client = OllamaChatClient(
        base_url="http://127.0.0.1:11434",
        model="qwen2.5:1.5b",
        timeout_seconds=2.5,
        http_client=_Http(
            _Response(http_error=requests.exceptions.HTTPError("HTTP 500")),
            get_response=_Response({"models": [{"name": "qwen2.5:1.5b"}]}),
        ),
    )

    with pytest.raises(OllamaHealthCheckError, match="model present but tiny chat failed"):
        client.ping()


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
        model="qwen2.5:1.5b",
        timeout_seconds=30.0,
        http_client=_Http(_Response(payload)),
    )

    with pytest.raises(OllamaClientError):
        client.chat([{"role": "user", "content": "draft"}])


def test_ollama_client_wraps_http_failure() -> None:
    client = OllamaChatClient(
        base_url="http://127.0.0.1:11434",
        model="qwen2.5:1.5b",
        timeout_seconds=30.0,
        http_client=_Http(_Response(http_error=requests.exceptions.HTTPError("HTTP 500"))),
    )

    with pytest.raises(OllamaClientError, match="Ollama chat request failed"):
        client.chat([{"role": "user", "content": "draft"}])


def test_ollama_client_rejects_invalid_json() -> None:
    client = OllamaChatClient(
        base_url="http://127.0.0.1:11434",
        model="qwen2.5:1.5b",
        timeout_seconds=30.0,
        http_client=_Http(_Response(json_error=ValueError("bad json"))),
    )

    with pytest.raises(OllamaClientError, match="invalid JSON"):
        client.chat([{"role": "user", "content": "draft"}])
