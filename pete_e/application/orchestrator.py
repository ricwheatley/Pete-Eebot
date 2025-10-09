# pete_e/application/orchestrator.py
"""
Main orchestrator for Pete-Eebot's core logic. This refactored version
delegates tasks to specialized services for clarity and maintainability.
"""
from __future__ import annotations
from datetime import date, timedelta
from typing import Dict, Any, NamedTuple
from dataclasses import dataclass

# --- NEW Clean Imports ---
from pete_e.application.services import PlanService, WgerExportService
from pete_e.infrastructure.postgres_dal import PostgresDal
from pete_e.infrastructure.wger_client import WgerClient
from pete_e.domain.validation import validate_and_adjust_plan, ValidationDecision
from pete_e.domain.cycle_service import CycleService
from pete_e.infrastructure import log_utils

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
        dal: PostgresDal,
        wger_client: WgerClient,
        plan_service: PlanService,
        export_service: WgerExportService,
    ):
        """
        Initializes the orchestrator with the dependencies it requires.
        """
        self.dal = dal
        self.wger_client = wger_client
        self.plan_service = plan_service
        self.export_service = export_service

    def run_weekly_calibration(self, reference_date: date) -> WeeklyCalibrationResult:
        """
        Runs validation and progression on the upcoming week.
        This method is now much simpler.
        """
        log_utils.info(f"Running weekly calibration for week starting after {reference_date.isoformat()}")
        
        # The core validation logic remains, but it's now the main focus of this method.
        # The complex plan-finding logic will be handled by the services it calls.
        next_monday = reference_date + timedelta(days=(7 - reference_date.weekday()))
        validation_decision = validate_and_adjust_plan(self.dal, next_monday)
        
        return WeeklyCalibrationResult(
            message=validation_decision.explanation,
            validation=validation_decision
        )

    def run_cycle_rollover(self, reference_date: date) -> CycleRolloverResult:
        """
        Handles the end-of-cycle logic: creating the next block and exporting week 1.
        This is now a clean, high-level workflow.
        """
        next_monday = reference_date + timedelta(days=(7 - reference_date.weekday()))
        log_utils.info(f"Cycle rollover triggered for block starting {next_monday.isoformat()}")

        try:
            # 1. Delegate plan creation to the PlanService
            # The service now contains all the logic for deciding if a test week or
            # a standard block is needed, and for building and saving it.
            # (Assuming a method in PlanService that encapsulates this logic)
            plan_id = self.plan_service.create_next_plan_for_cycle(start_date=next_monday)
            if not plan_id:
                raise RuntimeError("Plan creation returned an invalid ID.")

            # 2. Delegate the export to the WgerExportService
            self.export_service.export_plan_week(
                plan_id=plan_id,
                week_number=1,
                start_date=next_monday,
                force_overwrite=True
            )
            
            return CycleRolloverResult(
                plan_id=plan_id,
                created=True,
                exported=True,
                message=f"New cycle started with plan {plan_id} and week 1 exported."
            )

        except Exception as e:
            log_utils.error(f"Cycle rollover failed: {e}", "ERROR")
            return CycleRolloverResult(
                plan_id=None, created=False, exported=False, message=str(e)
            )

    def run_end_to_end_week(self, reference_date: date | None = None) -> WeeklyAutomationResult:
        """
        The main entry point for the Sunday review.
        """
        today = reference_date or date.today()
        
        # Run calibration on the upcoming week
        calibration_result = self.run_weekly_calibration(today)
        
        # Decide if a rollover is needed (simplified logic)
        rollover_triggered = False
        rollover_result = None
        
        # Example: Trigger rollover on the last Sunday of a 4-week block
        active_plan = self.dal.get_active_plan()
        if CycleService.should_rollover(active_plan, today):
            rollover_triggered = True

        if rollover_triggered:
            rollover_result = self.run_cycle_rollover(today)

        return WeeklyAutomationResult(
            calibration=calibration_result,
            rollover=rollover_result,
            rollover_triggered=rollover_triggered
        )
        
    def close(self):
        """Closes any open connections, like the database pool."""
        self.dal.close()
