from __future__ import annotations

from typing import Any, Dict, Mapping, Type

from pete_e.application.services import PlanService, WgerExportService
from pete_e.infrastructure.di_container import build_container
from pete_e.infrastructure.postgres_dal import PostgresDal
from pete_e.infrastructure.wger_client import WgerClient

ServiceType = Type[Any]


def build_stub_container(
    *,
    dal: Any | None = None,
    wger_client: Any | None = None,
    plan_service: Any | None = None,
    export_service: Any | None = None,
    extra_overrides: Mapping[ServiceType, Any] | None = None,
):
    """Construct a container seeded with stubbed dependencies for tests."""
    overrides: Dict[ServiceType, Any] = {}
    if dal is not None:
        overrides[PostgresDal] = dal
    if wger_client is not None:
        overrides[WgerClient] = wger_client
    if plan_service is not None:
        overrides[PlanService] = plan_service
    if export_service is not None:
        overrides[WgerExportService] = export_service
    if extra_overrides:
        overrides.update(extra_overrides)
    return build_container(overrides=overrides or None)


__all__ = ["build_stub_container"]
