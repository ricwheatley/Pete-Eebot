# pete_e/infrastructure/di_container.py
"""Dependency injection container for Pete-E services."""
from __future__ import annotations

from functools import lru_cache
import inspect
from typing import Any, Callable, Dict, Type

from pete_e.application.composition import (
    provide_apple_dropbox_client,
    provide_apple_health_ingestor,
    provide_cycle_service,
    provide_daily_sync_service,
    provide_plan_service,
    provide_postgres_dal,
    provide_telegram_client,
    provide_user_service,
    provide_validation_service,
    provide_wger_client,
    provide_wger_export_service,
    provide_withings_client,
)
from pete_e.application.services import PlanService, WgerExportService
from pete_e.application.user_service import UserService
from pete_e.application.validation_service import ValidationService
from pete_e.config import settings as app_settings
from pete_e.domain.configuration import DomainSettings, configure as configure_domain
from pete_e.domain.cycle_service import CycleService
from pete_e.domain.daily_sync import AppleHealthIngestor, DailySyncService
from pete_e.infrastructure.apple_dropbox_client import AppleDropboxClient
from pete_e.infrastructure.postgres_dal import PostgresDal
from pete_e.infrastructure.telegram_client import TelegramClient
from pete_e.infrastructure.wger_client import WgerClient
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
        """Initialize this object."""

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
        """Perform register."""

    def resolve(self, service: ServiceType) -> Any:
        if service in self._instances:
            return self._instances[service]
        try:
            factory = self._factories[service]
        except KeyError as exc:
            raise KeyError(f"No provider registered for {service!r}") from exc
        return factory(self)
        """Perform resolve."""


def _register_defaults(container: Container) -> None:
    """Register the production service graph with the container."""
    container.register(PostgresDal, factory=lambda _c: provide_postgres_dal())
    container.register(WgerClient, factory=lambda _c: provide_wger_client())
    container.register(AppleDropboxClient, factory=lambda _c: provide_apple_dropbox_client())
    container.register(WithingsClient, factory=lambda _c: provide_withings_client())
    container.register(TelegramClient, factory=lambda _c: provide_telegram_client())
    container.register(
        AppleHealthIngestor,
        factory=lambda c: provide_apple_health_ingestor(
            dal=c.resolve(PostgresDal),
            client=c.resolve(AppleDropboxClient),
        ),
    )
    container.register(PlanService, factory=lambda c: provide_plan_service(dal=c.resolve(PostgresDal)))
    container.register(UserService, factory=lambda c: provide_user_service(dal=c.resolve(PostgresDal)))
    container.register(
        WgerExportService,
        factory=lambda c: provide_wger_export_service(
            dal=c.resolve(PostgresDal),
            wger_client=c.resolve(WgerClient),
        ),
    )
    container.register(
        DailySyncService,
        factory=lambda c: provide_daily_sync_service(
            repository=c.resolve(PostgresDal),
            withings_source=c.resolve(WithingsClient),
            apple_ingestor=c.resolve(AppleHealthIngestor),
        ),
    )
    container.register(ValidationService, factory=lambda c: provide_validation_service(dal=c.resolve(PostgresDal)))
    container.register(CycleService, factory=lambda _c: provide_cycle_service())


def _wrap_override(provider: Any) -> Factory:
    if inspect.isfunction(provider) or inspect.ismethod(provider):
        signature = inspect.signature(provider)
        if len(signature.parameters) == 0:
            return lambda _c, fn=provider: fn()
        return lambda c, fn=provider: fn(c)
    if isinstance(provider, type):
        return lambda _c, cls=provider: cls()
    return lambda _c, value=provider: value
    """Perform wrap override."""


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
