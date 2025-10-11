# pete_e/infrastructure/di_container.py
"""Dependency injection container for Pete-E services."""
from __future__ import annotations

from functools import lru_cache
import inspect
from typing import Any, Callable, Dict, Type

from pete_e.application.services import PlanService, WgerExportService
from pete_e.config import settings as app_settings
from pete_e.domain.configuration import DomainSettings, configure as configure_domain
from pete_e.domain.daily_sync import AppleHealthIngestor, DailySyncService
from pete_e.infrastructure.apple_dropbox_client import AppleDropboxClient
from pete_e.infrastructure.apple_health_ingestor import AppleHealthDropboxIngestor
from pete_e.infrastructure.postgres_dal import PostgresDal
from pete_e.infrastructure.telegram_client import TelegramClient
from pete_e.infrastructure.wger_client import WgerClient
from pete_e.infrastructure.token_storage import JsonFileTokenStorage
from pete_e.infrastructure.withings_client import WithingsClient

configure_domain(
    DomainSettings(
        progression_increment=app_settings.PROGRESSION_INCREMENT,
        progression_decrement=app_settings.PROGRESSION_DECREMENT,
        rhr_allowed_increase=app_settings.RHR_ALLOWED_INCREASE,
        sleep_allowed_decrease=app_settings.SLEEP_ALLOWED_DECREASE,
        hrv_allowed_decrease=app_settings.HRV_ALLOWED_DECREASE,
        body_age_allowed_increase=app_settings.BODY_AGE_ALLOWED_INCREASE,
        global_backoff_factor=app_settings.GLOBAL_BACKOFF_FACTOR,
        baseline_days=app_settings.BASELINE_DAYS,
        cycle_days=app_settings.CYCLE_DAYS,
        phrases_path=app_settings.phrases_path,
    )
)

ServiceType = Type[Any]
Factory = Callable[["Container"], Any]


class Container:
    """Minimal service container supporting factories and instances."""

    def __init__(self) -> None:
        self._factories: Dict[ServiceType, Factory] = {}
        self._instances: Dict[ServiceType, Any] = {}

    def register(
        self,
        service: ServiceType,
        *,
        factory: Factory | None = None,
        instance: Any | None = None,
    ) -> None:
        if instance is not None:
            self._instances[service] = instance
            self._factories.pop(service, None)
            return
        if factory is None:
            raise ValueError("Either factory or instance must be provided.")
        self._factories[service] = factory
        self._instances.pop(service, None)

    def resolve(self, service: ServiceType) -> Any:
        if service in self._instances:
            return self._instances[service]
        try:
            factory = self._factories[service]
        except KeyError as exc:
            raise KeyError(f"No provider registered for {service!r}") from exc
        return factory(self)


def _register_defaults(container: Container) -> None:
    """Register the production service graph with the container."""
    container.register(PostgresDal, factory=lambda _c: PostgresDal())
    container.register(WgerClient, factory=lambda _c: WgerClient())
    container.register(AppleDropboxClient, factory=lambda _c: AppleDropboxClient())
    container.register(
        WithingsClient,
        factory=lambda _c: WithingsClient(token_storage=JsonFileTokenStorage(WithingsClient.TOKEN_FILE)),
    )
    container.register(TelegramClient, factory=lambda _c: TelegramClient())
    container.register(
        AppleHealthIngestor,
        factory=lambda c: AppleHealthDropboxIngestor(
            dal=c.resolve(PostgresDal),
            client=c.resolve(AppleDropboxClient),
        ),
    )
    container.register(PlanService, factory=lambda c: PlanService(c.resolve(PostgresDal)))
    container.register(
        WgerExportService,
        factory=lambda c: WgerExportService(
            dal=c.resolve(PostgresDal),
            wger_client=c.resolve(WgerClient),
        ),
    )
    container.register(
        DailySyncService,
        factory=lambda c: DailySyncService(
            repository=c.resolve(PostgresDal),
            withings_source=c.resolve(WithingsClient),
            apple_ingestor=c.resolve(AppleHealthIngestor),
        ),
    )


def _wrap_override(provider: Any) -> Factory:
    if inspect.isfunction(provider) or inspect.ismethod(provider):
        signature = inspect.signature(provider)
        if len(signature.parameters) == 0:
            return lambda _c, fn=provider: fn()
        return lambda c, fn=provider: fn(c)
    if isinstance(provider, type):
        return lambda _c, cls=provider: cls()
    return lambda _c, value=provider: value


def build_container(overrides: Dict[ServiceType, Any] | None = None) -> Container:
    """Create a new container with optional dependency overrides."""
    container = Container()
    _register_defaults(container)

    if overrides:
        for service, provider in overrides.items():
            factory = _wrap_override(provider)
            if isinstance(provider, (type,)) or inspect.isfunction(provider) or inspect.ismethod(provider):
                container.register(service, factory=factory)
            else:
                container.register(service, instance=factory(container))

    return container


@lru_cache(maxsize=1)
def get_container() -> Container:
    """Return a cached container instance for application use."""
    return build_container()


__all__ = ["Container", "build_container", "get_container"]