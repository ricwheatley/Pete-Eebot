from __future__ import annotations

from pete_e import observability
from pete_e.application import alerts
from pete_e.application.adapter_contracts import (
    AdapterHealth,
    AdapterMetadata,
    DataProviderAdapter,
    DataProviderSyncRequest,
    DataProviderSyncResult,
    NotificationChannel,
    NotificationDeliveryResult,
    NotificationMessage,
)
from pete_e.infrastructure.di_container import build_container
from pete_e.infrastructure.telegram_client import TelegramClient
from pete_e.infrastructure.telegram_notification_channel import TelegramNotificationChannel


class _ExampleProvider:
    @property
    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            name="example-provider",
            kind="data_provider",
            capabilities=("sync", "health_check"),
        )

    def health_check(self) -> AdapterHealth:
        return AdapterHealth(status="ok", detail="ready")

    def sync(self, request: DataProviderSyncRequest) -> DataProviderSyncResult:
        return DataProviderSyncResult(
            provider=self.metadata.name,
            success=True,
            records_processed=request.days_back,
            statuses={self.metadata.name: "ok"},
        )


class _StubTelegram:
    def __init__(self, *, delivered: bool = True) -> None:
        self.delivered = delivered
        self.alerts: list[str] = []
        self.messages: list[str] = []

    def ping(self) -> str:
        return "telegram ready"

    def send_alert(self, message: str) -> bool:
        self.alerts.append(message)
        return self.delivered

    def send_message(self, message: str) -> bool:
        self.messages.append(message)
        return self.delivered


class _CapturingChannel:
    def __init__(self) -> None:
        self.messages: list[NotificationMessage] = []

    @property
    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(name="capture", kind="notification_channel")

    def health_check(self) -> AdapterHealth:
        return AdapterHealth(status="ok", detail="ready")

    def send(self, message: NotificationMessage) -> NotificationDeliveryResult:
        self.messages.append(message)
        return NotificationDeliveryResult(channel=self.metadata.name, success=True)


def test_data_provider_adapter_contract_accepts_reference_shape() -> None:
    provider = _ExampleProvider()

    assert isinstance(provider, DataProviderAdapter)
    result = provider.sync(DataProviderSyncRequest(days_back=3))

    assert result.success is True
    assert result.records_processed == 3
    assert result.statuses == {"example-provider": "ok"}


def test_telegram_notification_channel_implements_notification_contract() -> None:
    client = _StubTelegram()
    channel = TelegramNotificationChannel(client=client)  # type: ignore[arg-type]

    assert isinstance(channel, NotificationChannel)
    health = channel.health_check()
    delivery = channel.send(NotificationMessage(body="P1 test alert", severity="P1"))

    assert channel.metadata.name == "telegram"
    assert health == AdapterHealth(
        status="ok",
        detail="telegram ready",
        checked_at=health.checked_at,
    )
    assert health.checked_at is not None
    assert delivery == NotificationDeliveryResult(
        channel="telegram",
        success=True,
        context={"severity": "P1", "dedupe_key": None},
    )
    assert client.alerts == ["P1 test alert"]
    assert client.messages == []


def test_telegram_notification_channel_sends_non_alert_messages_plain() -> None:
    client = _StubTelegram()
    channel = TelegramNotificationChannel(client=client)  # type: ignore[arg-type]

    delivery = channel.send(NotificationMessage(body="daily summary ready"))

    assert delivery.success is True
    assert client.messages == ["daily summary ready"]
    assert client.alerts == []


def test_container_registers_telegram_notification_channel() -> None:
    client = _StubTelegram()
    container = build_container(overrides={TelegramClient: client})

    channel = container.resolve(NotificationChannel)

    assert isinstance(channel, TelegramNotificationChannel)
    assert channel.health_check().ok is True


def test_alert_delivery_uses_notification_channel_contract(monkeypatch) -> None:
    observability.reset_metrics()
    alerts.reset_alert_state()
    channel = _CapturingChannel()
    monkeypatch.setenv("PETEEEBOT_ALERT_TELEGRAM_ENABLED", "1")
    monkeypatch.setenv("PETEEEBOT_ALERT_DEDUPE_SECONDS", "0")
    monkeypatch.setattr(alerts, "_get_notification_channel", lambda: channel)

    emitted = alerts.emit_alert(
        alerts.AlertEvent(
            alert_type=alerts.ALERT_AUTH_EXPIRY,
            severity=alerts.SEVERITY_P2,
            title="Withings authorization needs attention",
            summary="Withings token expired",
            dedupe_key="auth_expiry:Withings",
            context={"provider": "Withings"},
        )
    )

    assert emitted is True
    assert len(channel.messages) == 1
    message = channel.messages[0]
    assert message.title == "Withings authorization needs attention"
    assert message.severity == "P2"
    assert message.dedupe_key == "auth_expiry:Withings"
    assert "Withings token expired" in message.body
    assert message.context["alert_type"] == alerts.ALERT_AUTH_EXPIRY
    assert message.context["provider"] == "Withings"


def test_notification_delivery_failure_does_not_break_alert(monkeypatch) -> None:
    class FailingChannel(_CapturingChannel):
        def send(self, message: NotificationMessage) -> NotificationDeliveryResult:
            self.messages.append(message)
            return NotificationDeliveryResult(channel="capture", success=False, error="offline")

    observability.reset_metrics()
    alerts.reset_alert_state()
    channel = FailingChannel()
    monkeypatch.setenv("PETEEEBOT_ALERT_TELEGRAM_ENABLED", "1")
    monkeypatch.setenv("PETEEEBOT_ALERT_DEDUPE_SECONDS", "0")
    monkeypatch.setattr(alerts, "_get_notification_channel", lambda: channel)

    emitted = alerts.emit_alert(
        alerts.AlertEvent(
            alert_type=alerts.ALERT_STALE_INGEST,
            severity=alerts.SEVERITY_P1,
            title="Apple Health ingest is stale",
            summary="No Apple Health data imported recently",
            dedupe_key="stale_ingest:Apple Health",
        )
    )

    assert emitted is True
    assert len(channel.messages) == 1
