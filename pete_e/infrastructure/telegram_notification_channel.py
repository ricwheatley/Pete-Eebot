"""Notification channel adapter for Telegram."""

from __future__ import annotations

from datetime import datetime, timezone

from pete_e.application.adapter_contracts import (
    AdapterHealth,
    AdapterMetadata,
    NotificationDeliveryResult,
    NotificationMessage,
)
from pete_e.infrastructure.telegram_client import TelegramClient


class TelegramNotificationChannel:
    """Reference notification adapter backed by the Telegram Bot API."""

    def __init__(self, client: TelegramClient | None = None) -> None:
        self._client = client

    @property
    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            name="telegram",
            kind="notification_channel",
            display_name="Telegram",
            description="Sends Pete-E operational and coaching messages to a Telegram chat.",
            capabilities=("message", "alert", "health_check"),
        )

    def health_check(self) -> AdapterHealth:
        try:
            detail = self._get_client().ping()
        except Exception as exc:
            return AdapterHealth(
                status="failed",
                detail=str(exc),
                checked_at=datetime.now(timezone.utc),
            )
        return AdapterHealth(
            status="ok",
            detail=detail,
            checked_at=datetime.now(timezone.utc),
        )

    def send(self, message: NotificationMessage) -> NotificationDeliveryResult:
        body = (message.body or "").strip()
        if not body:
            return NotificationDeliveryResult(
                channel=self.metadata.name,
                success=False,
                error="message body is empty",
            )

        client = self._get_client()
        delivered = client.send_alert(body) if message.severity else client.send_message(body)
        return NotificationDeliveryResult(
            channel=self.metadata.name,
            success=bool(delivered),
            error=None if delivered else "Telegram send returned False",
            context={
                "severity": message.severity,
                "dedupe_key": message.dedupe_key,
            },
        )

    def _get_client(self) -> TelegramClient:
        if self._client is not None:
            return self._client
        from pete_e.infrastructure.di_container import get_container

        return get_container().resolve(TelegramClient)


__all__ = ["TelegramNotificationChannel"]
