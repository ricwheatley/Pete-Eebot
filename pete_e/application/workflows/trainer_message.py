from __future__ import annotations

from datetime import date
from typing import Any, Dict

from pete_e.application.exceptions import ApplicationError, DataAccessError
from pete_e.domain import french_trainer, metrics_service
from pete_e.infrastructure import log_utils


class TrainerMessageWorkflow:
    def __init__(self, *, dal, build_context):
        self.dal = dal
        self.build_context = build_context

    def run(self, message_date: date | None = None) -> str:
        target = message_date or date.today()
        try:
            metrics = metrics_service.get_metrics_overview(self.dal, reference_date=target)
        except ApplicationError:
            raise
        except Exception as exc:  # pragma: no cover
            message = f"Failed to load metrics for trainer message on {target.isoformat()}: {exc}"
            log_utils.error(message)
            raise DataAccessError(message) from exc

        context: Dict[str, Any] = self.build_context(target)
        try:
            return french_trainer.compose_daily_message(metrics, context)
        except Exception as exc:  # pragma: no cover
            message = f"Failed to compose trainer message for {target.isoformat()}: {exc}"
            log_utils.error(message)
            raise ApplicationError(message) from exc
