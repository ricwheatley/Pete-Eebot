"""Small Ollama chat client used for Pete's optional voice rewrite."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import requests

DEFAULT_CHAT_OPTIONS = {
    "temperature": 0.4,
    "num_predict": 220,
}


class OllamaClientError(RuntimeError):
    """Raised when Ollama cannot provide a usable chat response."""


class OllamaConnectionError(OllamaClientError):
    """Raised when the Ollama daemon cannot be reached or queried."""


class OllamaModelMissingError(OllamaClientError):
    """Raised when the configured model is not installed in Ollama."""


class OllamaChatClient:
    """Minimal client for Ollama's local ``/api/chat`` endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float,
        keep_alive: str | None = None,
        http_client: Any | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.keep_alive = str(keep_alive).strip() if keep_alive is not None else ""
        self._http = http_client or requests
        self._options = dict(options or DEFAULT_CHAT_OPTIONS)

    def chat(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        options: Mapping[str, Any] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "stream": False,
            "options": dict(options or self._options),
        }
        if self.keep_alive:
            payload["keep_alive"] = self.keep_alive

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

    def available_models(self) -> list[str]:
        """Return model names reported by Ollama's lightweight tags endpoint."""

        try:
            response = self._http.get(
                f"{self.base_url}/api/tags",
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as exc:
            raise OllamaConnectionError(f"Ollama unreachable: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise OllamaConnectionError("Ollama unreachable: /api/tags returned invalid JSON.") from exc

        if not isinstance(data, dict):
            raise OllamaConnectionError("Ollama unreachable: /api/tags response was not a JSON object.")

        models = data.get("models")
        if not isinstance(models, list):
            raise OllamaConnectionError("Ollama unreachable: /api/tags response missing models list.")

        names: list[str] = []
        for model in models:
            if not isinstance(model, dict):
                continue
            name = model.get("name") or model.get("model")
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
        return names

    def ping(self) -> str:
        """Confirm Ollama is reachable and the configured model is installed."""

        models = self.available_models()
        if self.model not in models:
            available = ", ".join(models) if models else "none"
            raise OllamaModelMissingError(
                f"configured model missing: {self.model} (available: {available})"
            )

        return f"{self.model} OK"
