"""Telegram Bot API client implementation."""

from __future__ import annotations

from typing import Any, Dict, Iterable

import requests

from pete_e.config import settings
from pete_e.infrastructure import log_utils

_REQUEST_TIMEOUT_SECONDS = 10


def _secret_to_str(value: Any) -> str:
    """Best-effort extraction of raw secret string values."""

    if value is None:
        return ""
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        try:
            return getter()
        except Exception:  # pragma: no cover - defensive
            pass
    return str(value)


def _scrub_sensitive(text: str, *, extras: Iterable[Any] | None = None) -> str:
    """Redacts known Telegram credentials from the outgoing message."""

    sanitized = text or ""
    secrets: list[Any] = [getattr(settings, attr, None) for attr in ("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID")]
    if extras:
        secrets.extend(extras)

    for secret in secrets:
        raw = _secret_to_str(secret)
        if not raw:
            continue
        for prefix in ("https://api.telegram.org/bot", "http://api.telegram.org/bot"):
            sanitized = sanitized.replace(f"{prefix}{raw}", f"{prefix}[redacted]")
        sanitized = sanitized.replace(f"bot{raw}", "bot[redacted]")
        sanitized = sanitized.replace(raw, "[redacted]")
    return sanitized


class TelegramClient:
    """Client responsible for interacting with the Telegram Bot API."""

    def __init__(
        self,
        *,
        token: str | None = None,
        chat_id: str | None = None,
        http_client: Any | None = None,
    ) -> None:
        self._token_override = _secret_to_str(token) if token is not None else None
        self._chat_id_override = _secret_to_str(chat_id) if chat_id is not None else None
        self._http = http_client or requests

    def _resolve_token(self) -> str:
        return self._token_override or _secret_to_str(getattr(settings, "TELEGRAM_TOKEN", None))

    def _resolve_chat_id(self) -> str:
        return self._chat_id_override or _secret_to_str(getattr(settings, "TELEGRAM_CHAT_ID", None))

    def _scrub(self, text: str) -> str:
        extras = [candidate for candidate in (
            self._token_override,
            self._chat_id_override,
            self._resolve_token(),
            self._resolve_chat_id(),
        ) if candidate]
        return _scrub_sensitive(text, extras=extras)

    def send_message(self, message: str, *, chat_id: str | None = None) -> bool:
        """Send a message to the configured Telegram chat."""

        token = self._resolve_token()
        target_chat_id = _secret_to_str(chat_id) if chat_id is not None else self._resolve_chat_id()

        if not token or not target_chat_id:
            log_utils.log_message(
                "Telegram token or chat_id not configured. Cannot send message.",
                "ERROR",
            )
            return False

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": target_chat_id, "text": message or ""}
        log_utils.log_message(f"Telegram payload preview: {payload}", "DEBUG")

        try:
            text = payload["text"]
            if len(text) > 4096:
                chunks = [text[i : i + 4000] for i in range(0, len(text), 4000)]
                for chunk in chunks:
                    self._http.post(
                        url,
                        json={**payload, "text": chunk},
                        timeout=_REQUEST_TIMEOUT_SECONDS,
                    ).raise_for_status()
                log_utils.log_message("Message split + sent in chunks.", "INFO")
                return True

            response = self._http.post(url, json=payload, timeout=_REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            log_utils.log_message("Successfully sent message to Telegram.", "INFO")
            return True

        except requests.exceptions.RequestException as exc:
            error_details = self._scrub(str(exc).strip() or exc.__class__.__name__)
            log_utils.log_message(
                f"Failed to send message to Telegram: {error_details}",
                "ERROR",
            )
            return False

    def get_updates(self, *, offset: int | None = None, limit: int = 10, timeout: int = 0) -> list[Dict[str, Any]]:
        """Poll Telegram for new updates using the configured bot credentials."""

        token = self._resolve_token()
        if not token:
            log_utils.log_message("Telegram token missing; cannot poll updates.", "WARN")
            return []

        url = f"https://api.telegram.org/bot{token}/getUpdates"
        bounded_limit = max(1, min(100, int(limit)))
        wait_timeout = max(0, int(timeout))
        params: Dict[str, Any] = {"limit": bounded_limit, "timeout": wait_timeout}
        if offset is not None:
            params["offset"] = int(offset)

        try:
            response = self._http.get(
                url,
                params=params,
                timeout=max(1, wait_timeout + 5),
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as exc:
            error_details = self._scrub(str(exc).strip() or exc.__class__.__name__)
            log_utils.log_message(
                f"Failed to fetch Telegram updates: {error_details}",
                "ERROR",
            )
            return []

        try:
            payload = response.json()
        except ValueError:
            log_utils.log_message("Telegram getUpdates returned invalid JSON.", "ERROR")
            return []

        if not isinstance(payload, dict) or not payload.get("ok"):
            status = payload.get("description") if isinstance(payload, dict) else "unknown error"
            log_utils.log_message(
                self._scrub(f"Telegram getUpdates failed: {status}"),
                "ERROR",
            )
            return []

        results = payload.get("result", [])
        if not isinstance(results, list):
            log_utils.log_message("Telegram getUpdates payload missing result list.", "ERROR")
            return []

        return results

    def send_alert(self, message: str) -> bool:
        """Send a high-priority alert via Telegram, redacting secrets first."""

        if not message:
            log_utils.log_message("Skipping Telegram alert because the message was empty.", "WARN")
            return False

        sanitized = self._scrub(message.strip())
        alert_text = f"[ALERT] {sanitized}"
        return self.send_message(alert_text)


__all__ = ["TelegramClient"]
