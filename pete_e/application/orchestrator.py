# pete_e/application/orchestrator.py
"""
Main orchestrator for Pete-Eebot's core logic.
Delegates tasks to specialized services for clarity and maintainability.
"""
from __future__ import annotations
from datetime import date, timedelta
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence

# --- NEW Clean Imports ---
from pete_e.application.exceptions import (
    ApplicationError,
    DataAccessError,
    PlanRolloverError,
    ValidationError,
)
from pete_e.application.plan_generation import PlanGenerationService  # 🆕 added
from pete_e.application.services import PlanService, WgerExportService
from pete_e.application.validation_service import ValidationService
from pete_e.domain import french_trainer, metrics_service
from pete_e.domain.cycle_service import CycleService
from pete_e.domain.daily_sync import DailySyncService
from pete_e.domain.narrative_builder import NarrativeBuilder
from pete_e.domain.validation import ValidationDecision
from pete_e.infrastructure import log_utils
from pete_e.infrastructure.di_container import Container, get_container
from pete_e.infrastructure.postgres_dal import PostgresDal
from pete_e.infrastructure.telegram_client import TelegramClient
from pete_e.infrastructure.wger_client import WgerClient


# --- Result dataclasses (unchanged) ---
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
    """Coordinates Pete-Eebot workflows by delegating to application services."""

    def __init__(
        self,
        *,
        container: Container | None = None,
        validation_service: ValidationService | None = None,
        cycle_service: CycleService | None = None,
        telegram_client: TelegramClient | None = None,
        narrative_builder: NarrativeBuilder | None = None,
    ):
        """Initialize orchestrator dependencies."""
        container = container or get_container()

        # Resolve shared dependencies
        self.dal = container.resolve(PostgresDal)
        self.wger_client = container.resolve(WgerClient)
        self.plan_service = container.resolve(PlanService)
        self.export_service = container.resolve(WgerExportService)
        self.daily_sync_service = container.resolve(DailySyncService)
        self.validation_service = validation_service or ValidationService(self.dal)
        self.cycle_service = cycle_service or CycleService()

        try:
            self.telegram_client = telegram_client or container.resolve(TelegramClient)
        except KeyError:
            self.telegram_client = telegram_client
            if self.telegram_client is None:
                log_utils.warn(
                    "TelegramClient dependency is unavailable; Telegram sends will be disabled."
                )

        self.narrative_builder = narrative_builder or NarrativeBuilder()

        # 🧩 NEW – integrated PlanGenerationService following same DI style
        try:
            self.plan_generation_service = PlanGenerationService(
                dal_factory=lambda: self.dal,
                wger_client_factory=lambda: self.wger_client,
            )
            log_utils.info("PlanGenerationService initialized successfully.")
        except Exception as exc:  # defensive guard
            self.plan_generation_service = None
            log_utils.error(f"Failed to initialize PlanGenerationService: {exc}")


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

        result = self.daily_sync_service.run_full(days=days)
        return result.as_tuple()

    def run_withings_only_sync(self, days: int):
        """Runs only the Withings portion of the sync and refreshes views."""
        result = self.daily_sync_service.run_withings_only(days=days)
        return result.as_tuple()

    def close(self):
        """Closes any open connections, like the database pool."""
        self.dal.close()

    # ------------------------------------------------------------------
    # Messaging helpers
    # ------------------------------------------------------------------

    def get_daily_summary(self, target_date: date | None = None) -> str:
        """Return the rendered daily summary narrative for the chosen day."""

        target = target_date or (date.today() - timedelta(days=1))
        try:
            summary_data = self.dal.get_daily_summary(target)
        except ApplicationError:
            raise
        except Exception as exc:  # pragma: no cover - defensive guard
            message = f"Failed to load daily summary for {target.isoformat()}: {exc}"
            log_utils.error(message)
            raise DataAccessError(message) from exc

        if not summary_data:
            return ""

        builder = self.narrative_builder or NarrativeBuilder()
        try:
            return builder.build_daily_summary(summary_data)
        except Exception as exc:  # pragma: no cover - defensive guard
            message = f"Failed to build daily summary for {target.isoformat()}: {exc}"
            log_utils.error(message)
            raise ApplicationError(message) from exc

    def build_trainer_message(self, message_date: date | None = None) -> str:
        """Compose Pierre's trainer check-in for the supplied date."""

        target = message_date or date.today()
        try:
            metrics = metrics_service.get_metrics_overview(
                self.dal, reference_date=target
            )
        except ApplicationError:
            raise
        except Exception as exc:  # pragma: no cover - defensive guard
            message = f"Failed to load metrics for trainer message on {target.isoformat()}: {exc}"
            log_utils.error(message)
            raise DataAccessError(message) from exc

        context = self._build_trainer_context(target)
        try:
            return french_trainer.compose_daily_message(metrics, context)
        except Exception as exc:  # pragma: no cover - defensive guard
            message = f"Failed to compose trainer message for {target.isoformat()}: {exc}"
            log_utils.error(message)
            raise ApplicationError(message) from exc

    def send_telegram_message(self, message: str) -> bool:
        """Proxy to the Telegram client while providing defensive logging."""

        if not message or not message.strip():
            log_utils.warn("Skipping Telegram send because the message was empty.")
            return False

        if self.telegram_client is None:
            log_utils.warn("No Telegram client available; cannot send message.")
            return False

        try:
            return bool(self.telegram_client.send_message(message))
        except Exception as exc:  # pragma: no cover - defensive guard
            log_utils.error(f"Telegram send failed: {exc}")
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_trainer_context(self, target: date) -> Dict[str, Any]:
        """Construct contextual hints for the trainer narrative."""

        context: Dict[str, Any] = {}
        plan_rows = self._load_plan_for_day(target)
        session_description = self._summarise_session(plan_rows)
        if session_description:
            context["today_session_type"] = session_description
        return context

    def _load_plan_for_day(self, target: date) -> Iterable[Dict[str, Any]]:
        """Fetch the active plan rows for the given day, normalising shape."""

        dal = getattr(self, "dal", None)
        if dal is None or not hasattr(dal, "get_plan_for_day"):
            return []

        try:
            columns, rows = dal.get_plan_for_day(target)
        except Exception as exc:  # pragma: no cover - defensive guard
            log_utils.warn(f"Failed to load plan for {target.isoformat()}: {exc}")
            return []

        if not rows:
            return []

        column_index = {name: idx for idx, name in enumerate(columns or [])}
        normalised: List[Dict[str, Any]] = []
        for row in rows:
            if isinstance(row, dict):
                normalised.append(dict(row))
                continue
            if not isinstance(row, Sequence) or isinstance(row, (str, bytes)):
                continue
            record: Dict[str, Any] = {}
            for name, idx in column_index.items():
                try:
                    value = row[idx]
                except (IndexError, TypeError):
                    continue
                record[name] = value
            if record:
                normalised.append(record)
        return normalised

    def _summarise_session(self, plan_rows: Iterable[Dict[str, Any]]) -> str | None:
        """Generate a short descriptor for the day's planned training."""

        rows = list(plan_rows)
        if not rows:
            return "Repos"

        seen: List[str] = []
        for row in rows:
            name = row.get("exercise_name")
            if not name:
                continue
            label = str(name).strip()
            if not label:
                continue
            if label not in seen:
                seen.append(label)
            if len(seen) == 3:
                break

        if not seen:
            return "Seance d'entraînement"
        if len(seen) == 1:
            return seen[0]
        if len(seen) == 2:
            return f"{seen[0]} & {seen[1]}"
        return f"{seen[0]}, {seen[1]} + more"
