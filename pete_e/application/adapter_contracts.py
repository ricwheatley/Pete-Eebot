"""Formal extension contracts for data providers and notification channels."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Mapping, Protocol, Sequence, runtime_checkable

AdapterKind = Literal["data_provider", "notification_channel"]
HealthStatus = Literal["ok", "degraded", "failed"]


@dataclass(frozen=True)
class AdapterMetadata:
    """Human and machine readable description of an extension adapter."""

    name: str
    kind: AdapterKind
    version: str = "1.0"
    display_name: str | None = None
    description: str | None = None
    capabilities: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class AdapterHealth:
    """Health check result returned by all adapters."""

    status: HealthStatus
    detail: str
    checked_at: datetime | None = None
    context: Mapping[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass(frozen=True)
class DataProviderSyncRequest:
    """Generic sync request passed to data provider adapters."""

    days_back: int = 1
    since: datetime | None = None
    context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DataProviderSyncResult:
    """Generic result returned by data provider adapters."""

    provider: str
    success: bool
    records_processed: int = 0
    failures: Sequence[str] = field(default_factory=tuple)
    statuses: Mapping[str, str] = field(default_factory=dict)
    alerts: Sequence[str] = field(default_factory=tuple)
    context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NotificationMessage:
    """Message envelope accepted by notification channel adapters."""

    body: str
    title: str | None = None
    severity: str | None = None
    dedupe_key: str | None = None
    context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NotificationDeliveryResult:
    """Result returned by notification channel adapters."""

    channel: str
    success: bool
    provider_message_id: str | None = None
    error: str | None = None
    context: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class DataProviderAdapter(Protocol):
    """Contract implemented by adapters that import or sync upstream data."""

    @property
    def metadata(self) -> AdapterMetadata:
        """Return adapter metadata for registration, docs, and UI display."""

    def health_check(self) -> AdapterHealth:
        """Return adapter reachability/configuration status."""

    def sync(self, request: DataProviderSyncRequest) -> DataProviderSyncResult:
        """Synchronise upstream data for the supplied request."""


@runtime_checkable
class NotificationChannel(Protocol):
    """Contract implemented by adapters that deliver notifications."""

    @property
    def metadata(self) -> AdapterMetadata:
        """Return adapter metadata for registration, docs, and UI display."""

    def health_check(self) -> AdapterHealth:
        """Return channel reachability/configuration status."""

    def send(self, message: NotificationMessage) -> NotificationDeliveryResult:
        """Deliver a notification message."""


@runtime_checkable
class AdapterPlugin(Protocol):
    """Optional bundle interface for registering related adapters together."""

    @property
    def metadata(self) -> AdapterMetadata:
        """Return plugin metadata."""

    def data_providers(self) -> Sequence[DataProviderAdapter]:
        """Return data provider adapters supplied by the plugin."""

    def notification_channels(self) -> Sequence[NotificationChannel]:
        """Return notification channel adapters supplied by the plugin."""


__all__ = [
    "AdapterHealth",
    "AdapterKind",
    "AdapterMetadata",
    "AdapterPlugin",
    "DataProviderAdapter",
    "DataProviderSyncRequest",
    "DataProviderSyncResult",
    "HealthStatus",
    "NotificationChannel",
    "NotificationDeliveryResult",
    "NotificationMessage",
]
