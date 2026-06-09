"""Small Ollama chat client used for Pete's optional voice rewrite."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import requests


class OllamaClientError(RuntimeError):
    """Raised when Ollama cannot provide a usable chat response."""


class OllamaChatClient:
    """Minimal client for Ollama's local ``/api/chat`` endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float,
        http_client: Any | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._http = http_client or requests

    def chat(self, messages: Sequence[Mapping[str, str]]) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "stream": False,
            "options": {
                "temperature": 0.2,
                "top_p": 0.8,
                "repeat_penalty": 1.05,
            },
        }

        try:
            response = self._http.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as exc:
            raise OllamaClientError(f"Ollama chat request failed: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise OllamaClientError("Ollama chat returned invalid JSON.") from exc

        if not isinstance(data, dict):
            raise OllamaClientError("Ollama chat response was not a JSON object.")

        message = data.get("message")
        if not isinstance(message, dict):
            raise OllamaClientError("Ollama chat response missing message object.")

        content = message.get("content")
        if not isinstance(content, str):
            raise OllamaClientError("Ollama chat response missing message content.")

        rewritten = content.strip()
        if not rewritten:
            raise OllamaClientError("Ollama chat response content was empty.")

        return rewritten

    def ping(self) -> str:
        """Confirm the configured Ollama model can answer a chat request."""

        self.chat(
            [
                {"role": "system", "content": "Reply with a short health check acknowledgement."},
                {"role": "user", "content": "health check"},
            ]
        )
        return f"{self.model} reachable"
