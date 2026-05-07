from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

from pete_e.application.collaborator_contracts import ExportContract, PlanGenerationContract
from pete_e.application.exceptions import ApplicationError, PlanRolloverError
from pete_e.domain.validation import ValidationDecision
from pete_e.infrastructure import log_utils


@dataclass(frozen=True)
class CycleRolloverResult:
    plan_id: int | None
    created: bool
    exported: bool
    message: str | None = None


class CycleRolloverWorkflow:
    def __init__(
        self,
        *,
        plan_service: PlanGenerationContract,
        export_service: ExportContract,
        hold_plan_generation_lock: Callable[[], AbstractContextManager],
    ):
        self.plan_service = plan_service
        self.export_service = export_service
        self.hold_plan_generation_lock = hold_plan_generation_lock

    def run(
        self,
        reference_date: date,
        *,
        validation_decision: ValidationDecision | None = None,
    ) -> CycleRolloverResult:
        next_monday = reference_date + timedelta(days=(7 - reference_date.weekday()))
        log_utils.info(f"Cycle rollover triggered for block starting {next_monday.isoformat()}")

        with self.hold_plan_generation_lock():
            try:
                plan_id = self.plan_service.create_next_plan_for_cycle(start_date=next_monday)
            except ApplicationError:
                raise
            except Exception as exc:  # pragma: no cover
                message = f"Plan creation failed for cycle starting {next_monday.isoformat()}: {exc}"
                log_utils.error(message, "ERROR")
                raise PlanRolloverError(message) from exc

            if not plan_id:
                message = f"Plan creation returned an invalid ID for cycle starting {next_monday.isoformat()}"
                log_utils.error(message, "ERROR")
                raise PlanRolloverError(message)

            try:
                self.export_service.export_plan_week(
                    plan_id=plan_id,
                    week_number=1,
                    start_date=next_monday,
                    force_overwrite=True,
                    validation_decision=validation_decision,
                )
            except ApplicationError:
                raise
            except Exception as exc:  # pragma: no cover
                message = f"Export failed for plan {plan_id} week 1 starting {next_monday.isoformat()}: {exc}"
                log_utils.error(message, "ERROR")
                raise PlanRolloverError(message) from exc

        return CycleRolloverResult(
            plan_id=plan_id,
            created=True,
            exported=True,
            message=f"New cycle started with plan {plan_id} and week 1 exported.",
        )
