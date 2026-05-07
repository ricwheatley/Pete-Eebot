from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from pete_e.application.collaborator_contracts import ValidationContract
from pete_e.application.exceptions import ApplicationError, ValidationError
from pete_e.domain.validation import ValidationDecision
from pete_e.infrastructure import log_utils


@dataclass(frozen=True)
class WeeklyCalibrationResult:
    message: str
    validation: ValidationDecision | None = None


class WeeklyCalibrationWorkflow:
    def __init__(self, validation_service: ValidationContract):
        self.validation_service = validation_service

    def run(self, reference_date: date) -> WeeklyCalibrationResult:
        next_monday = reference_date + timedelta(days=(7 - reference_date.weekday()))
        log_utils.info(
            f"Running weekly calibration for week starting {next_monday.isoformat()} "
            f"(review anchor {reference_date.isoformat()})"
        )

        try:
            validation_decision = self.validation_service.validate_and_adjust_plan(next_monday)
        except ApplicationError:
            raise
        except Exception as exc:  # pragma: no cover
            message = f"Weekly calibration failed for week starting {next_monday.isoformat()}: {exc}"
            log_utils.error(message)
            raise ValidationError(message) from exc

        return WeeklyCalibrationResult(
            message=validation_decision.explanation,
            validation=validation_decision,
        )
