"""Application dependency composition roots and provider helpers."""
from __future__ import annotations

from typing import Callable

from pete_e.application.adapter_contracts import NotificationChannel
from pete_e.application.services import PlanService, WgerExportService
from pete_e.application.user_service import UserService
from pete_e.application.validation_service import ValidationService
from pete_e.domain.cycle_service import CycleService
from pete_e.domain.daily_sync import AppleHealthIngestor, DailySyncService
from pete_e.domain.narrative_builder import NarrativeBuilder
from pete_e.infrastructure.apple_dropbox_client import AppleDropboxClient
from pete_e.infrastructure.apple_health_ingestor import AppleHealthDropboxIngestor
from pete_e.infrastructure.postgres_dal import PostgresDal
from pete_e.infrastructure.telegram_client import TelegramClient
from pete_e.infrastructure.telegram_notification_channel import TelegramNotificationChannel
from pete_e.infrastructure.user_repository import PostgresUserRepository
from pete_e.infrastructure.token_storage import JsonFileTokenStorage
from pete_e.infrastructure.wger_client import WgerClient
from pete_e.infrastructure.withings_client import WithingsClient


def provide_postgres_dal() -> PostgresDal:
    return PostgresDal()


def provide_wger_client() -> WgerClient:
    return WgerClient()


def provide_apple_dropbox_client() -> AppleDropboxClient:
    return AppleDropboxClient()


def provide_withings_client() -> WithingsClient:
    return WithingsClient(token_storage=JsonFileTokenStorage(WithingsClient.TOKEN_FILE))


def provide_telegram_client() -> TelegramClient:
    return TelegramClient()


def provide_telegram_notification_channel(*, client: TelegramClient) -> NotificationChannel:
    return TelegramNotificationChannel(client=client)


def provide_apple_health_ingestor(*, dal: PostgresDal, client: AppleDropboxClient) -> AppleHealthIngestor:
    return AppleHealthDropboxIngestor(dal=dal, client=client)


def provide_plan_service(*, dal: PostgresDal) -> PlanService:
    return PlanService(dal)


def provide_user_service(*, dal: PostgresDal) -> UserService:
    return UserService(PostgresUserRepository(pool=dal.pool))


def provide_wger_export_service(*, dal: PostgresDal, wger_client: WgerClient) -> WgerExportService:
    return WgerExportService(dal=dal, wger_client=wger_client)


def provide_daily_sync_service(
    *, repository: PostgresDal, withings_source: WithingsClient, apple_ingestor: AppleHealthIngestor
) -> DailySyncService:
    return DailySyncService(
        repository=repository,
        withings_source=withings_source,
        apple_ingestor=apple_ingestor,
    )


def provide_validation_service(*, dal: PostgresDal) -> ValidationService:
    return ValidationService(dal)


def provide_cycle_service() -> CycleService:
    return CycleService()


def provide_narrative_builder() -> NarrativeBuilder:
    return NarrativeBuilder()


OrchestratorFactory = Callable[..., object]
