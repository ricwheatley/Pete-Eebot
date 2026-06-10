from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict

from pete_e.application.exceptions import ApplicationError, DataAccessError
from pete_e.domain import french_trainer, metrics_service
from pete_e.infrastructure import log_utils


@dataclass(frozen=True)
class TrainerMessageContext:
    target: date
    metrics: Dict[str, Dict[str, Any]]
    context: Dict[str, Any]
    fallback_message: str


class TrainerMessageWorkflow:
    def __init__(self, *, dal, build_context):
        self.dal = dal
        self.build_context = build_context

    def run(self, message_date: date | None = None) -> str:
        return self.build_message_context(message_date).fallback_message

    def build_message_context(self, message_date: date | None = None) -> TrainerMessageContext:
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
            fallback = french_trainer.compose_daily_message(metrics, context)
        except Exception as exc:  # pragma: no cover
            message = f"Failed to compose trainer message for {target.isoformat()}: {exc}"
            log_utils.error(message)
            raise ApplicationError(message) from exc
        return TrainerMessageContext(
            target=target,
            metrics=metrics,
            context=context,
            fallback_message=fallback,
        )
