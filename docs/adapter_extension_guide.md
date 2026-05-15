# Adapter Extension Guide

Phase 5 extension points live in `pete_e.application.adapter_contracts`.
They define stable contracts for adding upstream data providers and
notification channels without changing orchestration code.

## Contracts

Use these protocol interfaces:

- `DataProviderAdapter`: imports or synchronises data from an upstream provider.
- `NotificationChannel`: delivers operational or coaching notifications.
- `AdapterPlugin`: optional bundle for grouping related provider/channel adapters.

All adapters expose `metadata` and `health_check()`. Metadata is used for
registration, operator display, and future plugin discovery. Health checks should
validate configuration and upstream reachability without mutating user data.

Data providers implement:

```python
def sync(self, request: DataProviderSyncRequest) -> DataProviderSyncResult:
    ...
```

Notification channels implement:

```python
def send(self, message: NotificationMessage) -> NotificationDeliveryResult:
    ...
```

## Reference Adapter

`pete_e.infrastructure.telegram_notification_channel.TelegramNotificationChannel`
is the reference notification adapter. It wraps `TelegramClient`, implements
`NotificationChannel`, and is registered in the DI container under the
`NotificationChannel` contract.

`pete_e.application.alerts.emit_alert()` now resolves `NotificationChannel`
instead of calling Telegram helpers directly. This keeps alerting independent of
the concrete delivery mechanism.

## Adding a Notification Channel

1. Create an infrastructure adapter module, for example
   `pete_e/infrastructure/slack_notification_channel.py`.
2. Implement `NotificationChannel`.
3. Return stable metadata:

```python
from pete_e.application.adapter_contracts import (
    AdapterHealth,
    AdapterMetadata,
    NotificationDeliveryResult,
    NotificationMessage,
)


class SlackNotificationChannel:
    @property
    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            name="slack",
            kind="notification_channel",
            display_name="Slack",
            capabilities=("message", "alert", "health_check"),
        )

    def health_check(self) -> AdapterHealth:
        return AdapterHealth(status="ok", detail="webhook configured")

    def send(self, message: NotificationMessage) -> NotificationDeliveryResult:
        # Call the upstream API here.
        return NotificationDeliveryResult(channel=self.metadata.name, success=True)
```

4. Add a provider function in `pete_e.application.composition`.
5. Register the implementation in `pete_e.infrastructure.di_container` under
   `NotificationChannel`, or add a feature flag/config selector if multiple
   channels should be available at once.
6. Add tests for successful send, failed send, health checks, and DI resolution.

## Adding a Data Provider

1. Create an infrastructure adapter for the upstream API.
2. Implement `DataProviderAdapter`.
3. Keep provider-specific payload parsing inside the adapter. Return canonical
   status, failure, alert, and record-count fields in `DataProviderSyncResult`.
4. Keep persistence either behind an injected repository or in an application
   service that consumes the provider result. Do not let API clients write to
   storage implicitly unless the existing workflow already owns that behavior.
5. Register the adapter in composition/DI and wire it into the relevant sync
   service.
6. Add tests for empty payloads, partial failures, retry/auth failure behavior,
   health checks, and the service path that consumes the adapter.

## Compatibility Rules

- Adapter names are stable IDs. Use lowercase kebab-case or snake_case and do
  not rename an adapter once persisted in logs/config.
- `health_check()` must not send user-visible messages or mutate imported data.
- `send()` must return `NotificationDeliveryResult(success=False, error=...)`
  for expected delivery failures instead of raising.
- Raise only for programmer errors or unrecoverable adapter defects.
- Scrub secrets before returning errors, logging context, or health details.
- Keep adapter constructors dependency-injection friendly: accept clients,
  repositories, or settings explicitly and provide sensible defaults only where
  the existing codebase already does so.
