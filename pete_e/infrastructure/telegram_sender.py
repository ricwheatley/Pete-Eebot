"""High-level helpers built on top of the Telegram client."""

from __future__ import annotations

from pete_e.infrastructure.di_container import get_container
from pete_e.infrastructure.telegram_client import TelegramClient


def _get_client(client: TelegramClient | None = None) -> TelegramClient:
    if client is not None:
        return client
    return get_container().resolve(TelegramClient)


def send_message(message: str, *, client: TelegramClient | None = None) -> bool:
    """Send a message to Telegram using the shared client."""

    return _get_client(client).send_message(message)


def get_updates(
    *,
    offset: int | None = None,
    limit: int = 10,
    timeout: int = 0,
    client: TelegramClient | None = None,
) -> list[dict]:
    """Fetch Telegram updates via the shared client."""

    return _get_client(client).get_updates(offset=offset, limit=limit, timeout=timeout)


def send_alert(message: str, *, client: TelegramClient | None = None) -> bool:
    """Send a high-priority Telegram alert using the shared client."""

    return _get_client(client).send_alert(message)


__all__ = ["get_updates", "send_alert", "send_message"]
