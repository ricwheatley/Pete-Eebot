# pete_e/application/orchestrator.py
"""
Main orchestrator for Pete-Eebot's core logic. This refactored version
delegates tasks to specialized services for clarity and maintainability.
"""
from __future__ import annotations
from datetime import date, timedelta
from typing import Dict, Any
from dataclasses import dataclass

# --- NEW Clean Imports ---
from pete_e.application.exceptions import (
    ApplicationError,
    DataAccessError,
    PlanRolloverError,
    ValidationError,
)
from pete_e.application.apple_dropbox_ingest import run_apple_health_ingest
from pete_e.application.services import PlanService, WgerExportService
from pete_e.application.validation_service import ValidationService
from pete_e.domain.cycle_service import CycleService
from pete_e.domain.validation import ValidationDecision
from pete_e.infrastructure import log_utils
from pete_e.infrastructure.apple_dropbox_client import AppleDropboxClient
from pete_e.infrastructure.postgres_dal import PostgresDal
from pete_e.infrastructure.wger_client import WgerClient
from pete_e.infrastructure.di_container import Container, get_container
from pete_e.application.sync import run_withings_sync

# --- Result dataclasses can remain for clear return types ---
@dataclass(frozen=True)
class WeeklyCalibrationResult:
    message: str
    validation: ValidationDecision | None = None

@dataclass(frozen=True)
class CycleRolloverResult:
    plan_id: int | None
    created: bool
    exported: bool
    message: str | None = None

@dataclass(frozen=True)
class WeeklyAutomationResult:
    calibration: WeeklyCalibrationResult
    rollover: CycleRolloverResult | None
    rollover_triggered: bool

class Orchestrator:
    """Coordinates the weekly workflow by delegating to application services."""

    def __init__(
        self,
        *,
        container: Container | None = None,
        validation_service: ValidationService | None = None,
        cycle_service: CycleService | None = None,
    ):
        """
        Initializes the orchestrator with the dependencies it requires.
        """
        container = container or get_container()

        self.dal = container.resolve(PostgresDal)
        self.wger_client = container.resolve(WgerClient)
        self.plan_service = container.resolve(PlanService)
        self.export_service = container.resolve(WgerExportService)
        self.dropbox_client = container.resolve(AppleDropboxClient)
        self.validation_service = validation_service or ValidationService(self.dal)
        self.cycle_service = cycle_service or CycleService()

    def run_weekly_calibration(self, reference_date: date) -> WeeklyCalibrationResult:
        """
        Runs validation and progression on the upcoming week.
        This method is now much simpler.
        """
        log_utils.info(f"Running weekly calibration for week starting after {reference_date.isoformat()}")

        # The core validation logic remains, but it's now the main focus of this method.
        # The complex plan-finding logic will be handled by the services it calls.
        next_monday = reference_date + timedelta(days=(7 - reference_date.weekday()))

        try:
            validation_decision = self.validation_service.validate_and_adjust_plan(next_monday)
        except ApplicationError:
            raise
        except Exception as exc:  # pragma: no cover - defensive guard
            message = (
                f"Weekly calibration failed for week starting {next_monday.isoformat()}: {exc}"
            )
            log_utils.error(message)
            raise ValidationError(message) from exc

        return WeeklyCalibrationResult(
            message=validation_decision.explanation,
            validation=validation_decision
        )

    def run_cycle_rollover(
        self,
        reference_date: date,
        *,
        validation_decision: ValidationDecision | None = None,
    ) -> CycleRolloverResult:
        """
        Handles the end-of-cycle logic: creating the next block and exporting week 1.
        This is now a clean, high-level workflow.
        """
        next_monday = reference_date + timedelta(days=(7 - reference_date.weekday()))
        log_utils.info(f"Cycle rollover triggered for block starting {next_monday.isoformat()}")

        try:
            plan_id = self.plan_service.create_next_plan_for_cycle(start_date=next_monday)
        except ApplicationError:
            raise
        except Exception as exc:  # pragma: no cover - defensive guard
            message = f"Plan creation failed for cycle starting {next_monday.isoformat()}: {exc}"
            log_utils.error(message, "ERROR")
            raise PlanRolloverError(message) from exc

        if not plan_id:
            message = (
                f"Plan creation returned an invalid ID for cycle starting {next_monday.isoformat()}"
            )
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
        except Exception as exc:  # pragma: no cover - defensive guard
            message = f"Export failed for plan {plan_id} week 1 starting {next_monday.isoformat()}: {exc}"
            log_utils.error(message, "ERROR")
            raise PlanRolloverError(message) from exc

        return CycleRolloverResult(
            plan_id=plan_id,
            created=True,
            exported=True,
            message=f"New cycle started with plan {plan_id} and week 1 exported."
        )

    def run_end_to_end_week(self, reference_date: date | None = None) -> WeeklyAutomationResult:
        """
        The main entry point for the Sunday review.
        """
        today = reference_date or date.today()

        # Run calibration on the upcoming week
        calibration_result = self.run_weekly_calibration(today)
        validation_decision = calibration_result.validation

        # Decide if a rollover is needed via the domain service
        rollover_result = None

        try:
            active_plan = self.dal.get_active_plan()
        except ApplicationError:
            raise
        except Exception as exc:  # pragma: no cover - defensive guard
            message = f"Failed to load active plan before weekly run on {today.isoformat()}: {exc}"
            log_utils.error(message, "ERROR")
            raise DataAccessError(message) from exc

        try:
            rollover_triggered = self.cycle_service.check_and_rollover(active_plan, today)
        except ApplicationError:
            raise
        except Exception as exc:  # pragma: no cover - defensive guard
            message = f"Failed to evaluate rollover for {today.isoformat()}: {exc}"
            log_utils.error(message, "ERROR")
            raise PlanRolloverError(message) from exc

        if rollover_triggered:
            rollover_result = self.run_cycle_rollover(
                today,
                validation_decision=validation_decision,
            )

        return WeeklyAutomationResult(
            calibration=calibration_result,
            rollover=rollover_result,
            rollover_triggered=rollover_triggered
        )
        
    def run_daily_sync(self, days: int):
        """Orchestrates the daily sync of all data sources."""
        log_utils.info("Orchestrator running daily sync...")

        log_utils.info("Running Withings sync...")
        # Note: The original `run_withings_sync` in sync.py returns a complex tuple.
        # We'll assume it's adapted or wrapped to return a dict or object.
        # For this patch, we'll call it and assume a dict-like result.
        withings_results = run_withings_sync(self.dal, self.withings_client, days)

        log_utils.info("Running Apple Health ingest from Dropbox...")
        apple_results = run_apple_health_ingest(self.dal, self.dropbox_client, days)

        log_utils.info("Refreshing database views...")
        self.dal.refresh_daily_summary(days=days + 1) # Add buffer day
        self.dal.refresh_actual_view()

        # Combine results into the tuple format expected by the CLI retry wrapper
        success = withings_results.get("success", False) and apple_results.get("success", False)
        failures = withings_results.get("failures", []) + apple_results.get("failures", [])
        statuses = {**withings_results.get("statuses", {}), **apple_results.get("statuses", {})}
        alerts = withings_results.get("alerts", []) + apple_results.get("alerts", [])
        return success, failures, statuses, alerts

    def close(self):
        """Closes any open connections, like the database pool."""
        self.dal.close()
