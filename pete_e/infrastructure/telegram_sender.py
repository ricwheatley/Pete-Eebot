"""Telegram Bot API helpers for Pete-Eebot."""

from __future__ import annotations

from typing import Any, Dict

import requests

from pete_e.config import settings
from pete_e.infrastructure import log_utils

_REQUEST_TIMEOUT_SECONDS = 10
_MD_V2_ESCAPE_MAP = {'!': '\\!',
 '#': '\\#',
 '(': '\\(',
 ')': '\\)',
 '*': '\\*',
 '+': '\\+',
 '-': '\\-',
 '.': '\\.',
 '=': '\\=',
 '>': '\\>',
 '[': '\\[',
 '\\': '\\\\',
 ']': '\\]',
 '_': '\\_',
 '`': '\\`',
 '{': '\\{',
 '|': '\\|',
 '}': '\\}',
 '~': '\\~'}
_MD_V2_TRANSLATION = str.maketrans(_MD_V2_ESCAPE_MAP)


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


def _scrub_sensitive(text: str) -> str:
    """Redacts known Telegram credentials from the outgoing message."""

    sanitized = text or ""
    for attr in ("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"):
        secret = getattr(settings, attr, None)
        raw = _secret_to_str(secret)
        if raw:
            sanitized = sanitized.replace(raw, "[redacted]")
    return sanitized


def _escape_markdown_v2_segment(text: str) -> str:
    if not text:
        return ""
    return text.translate(_MD_V2_TRANSLATION)


def escape_markdown_v2(message: str) -> str:
    """Escape a string for Telegram Markdown V2 parsing while keeping simple formatting."""

    if not message:
        return ""

    lines = message.split("\n")
    escaped_lines: list[str] = []
    for line in lines:
        if line == "":
            escaped_lines.append("")
            continue
        if line.startswith("*") and line.endswith("*") and len(line) > 1:
            inner = line[1:-1]
            escaped_lines.append(f"*{_escape_markdown_v2_segment(inner)}*")
            continue
        if line.startswith("- "):
            escaped_lines.append(f"- {_escape_markdown_v2_segment(line[2:])}")
            continue
        escaped_lines.append(_escape_markdown_v2_segment(line))

    return "\n".join(escaped_lines)





def send_message(message: str) -> bool:
    """Send a message to the configured Telegram chat."""

    token = _secret_to_str(getattr(settings, "TELEGRAM_TOKEN", None))
    chat_id = _secret_to_str(getattr(settings, "TELEGRAM_CHAT_ID", None))

    if not token or not chat_id:
        log_utils.log_message(
            "Telegram token or chat_id not configured. Cannot send message.",
            "ERROR",
        )
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    safe_text = escape_markdown_v2(message or "")
    payload = {
        "chat_id": chat_id,
        "text": safe_text,
        "parse_mode": "MarkdownV2",
    }
    try:
        response = requests.post(url, json=payload, timeout=_REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        log_utils.log_message("Successfully sent message to Telegram.", "INFO")
        return True
    except requests.RequestException as exc:
        error_details = _scrub_sensitive(str(exc).strip() or exc.__class__.__name__)
        log_utils.log_message(
            f"Failed to send message to Telegram: {error_details}",
            "ERROR",
        )
        return False


def get_updates(*, offset: int | None = None, limit: int = 10, timeout: int = 0) -> list[Dict[str, Any]]:
    """Poll Telegram for new updates using the configured bot credentials."""

    token = _secret_to_str(getattr(settings, "TELEGRAM_TOKEN", None))
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
        response = requests.get(
            url,
            params=params,
            timeout=max(1, wait_timeout + 5),
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        error_details = _scrub_sensitive(str(exc).strip() or exc.__class__.__name__)
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
            _scrub_sensitive(f"Telegram getUpdates failed: {status}"),
            "ERROR",
        )
        return []

    results = payload.get("result", [])
    if not isinstance(results, list):
        log_utils.log_message("Telegram getUpdates payload missing result list.", "ERROR")
        return []

    return results


def send_alert(message: str) -> bool:
    """Sends a high-priority alert via Telegram, redacting secrets first."""

    if not message:
        log_utils.log_message("Skipping Telegram alert because the message was empty.", "WARN")
        return False

    sanitized = _scrub_sensitive(message.strip())
    alert_text = f"[ALERT] {sanitized}"
    return send_message(alert_text)

