"""Application service responsible for generating training plans."""

from __future__ import annotations

import datetime as dt
from typing import Callable

import psycopg

from pete_e.application.services import PlanService, WgerExportService
from pete_e.infrastructure import log_utils
from pete_e.infrastructure.postgres_dal import PostgresDal
from pete_e.infrastructure.wger_client import WgerClient, WgerError


class PlanGenerationService:
    """Coordinates plan creation and optional export to wger."""

    def __init__(
        self,
        dal_factory: Callable[[], PostgresDal] | None = None,
        wger_client_factory: Callable[[], WgerClient] | None = None,
    ) -> None:
        self._dal_factory = dal_factory or PostgresDal
        self._wger_client_factory = wger_client_factory or WgerClient

    def run(self, start_date: dt.date, dry_run: bool = False) -> None:
        """Create a 5/3/1 block starting at ``start_date`` and export week one."""
        dal = self._dal_factory()
        wger_client = self._wger_client_factory()
        try:
            plan_service = PlanService(dal)
            export_service = WgerExportService(dal, wger_client)

            plan_id = plan_service.create_and_persist_531_block(start_date)
            log_utils.info(f"Successfully created plan_id: {plan_id}")

            export_result = export_service.export_plan_week(
                plan_id=plan_id,
                week_number=1,
                start_date=start_date,
                force_overwrite=True,
                dry_run=dry_run,
            )
            log_utils.info(f"Export result: {export_result}")
        except (psycopg.Error, WgerError) as exc:
            log_utils.error(f"Plan generation failed: {exc}", exc_info=True)
            raise
        finally:
            dal.close()
