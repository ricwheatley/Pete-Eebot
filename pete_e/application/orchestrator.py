# pete_e/application/orchestrator.py
"""
Main orchestrator for Pete-Eebot's core logic.
Delegates tasks to specialized services for clarity and maintainability.
"""
from __future__ import annotations
from contextlib import nullcontext
from datetime import date, datetime, timedelta
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence

# --- NEW Clean Imports ---
from pete_e.application.exceptions import (
    ApplicationError,
    DataAccessError,
    PlanRolloverError,
    ValidationError,
)
from pete_e.application.composition import (
    provide_coach_voice_service,
    provide_cycle_service,
    provide_narrative_builder,
    provide_validation_service,
)
from pete_e.application.coach_voice import CoachVoiceFact, CoachVoiceRequest, CoachVoiceService
from pete_e.application.collaborator_contracts import (
    CycleContract,
    DataAccessContract,
    ExportContract,
    MessagingContract,
    PlanGenerationContract,
    SyncContract,
    ValidationContract,
)
from pete_e.application.plan_generation import PlanGenerationService  # 🆕 added
from pete_e.application.plan_read_model import PlanReadModel
from pete_e.application.services import PlanService, WgerExportService
from pete_e.application.validation_service import ValidationService
from pete_e.application.workflows import (
    CycleRolloverWorkflow,
    DailySyncWorkflow,
    TrainerMessageWorkflow,
    WeeklyCalibrationWorkflow,
)
from pete_e.application.workflows.cycle_rollover import CycleRolloverResult
from pete_e.application.workflows.daily_sync import DailyAutomationResult
from pete_e.application.workflows.weekly_calibration import WeeklyCalibrationResult
from pete_e.domain import body_age, narrative_builder
from pete_e.domain.cycle_service import CycleService
from pete_e.domain.daily_sync import DailySyncService
from pete_e.domain.morning_coach import build_morning_training_adjustment
from pete_e.domain.narrative_builder import NarrativeBuilder, build_daily_narrative
from pete_e.domain.validation import ValidationDecision
from pete_e.infrastructure import log_utils
from pete_e.infrastructure.di_container import Container, get_container
from pete_e.infrastructure.postgres_dal import PostgresDal
from pete_e.infrastructure.telegram_client import TelegramClient
from pete_e.infrastructure.wger_client import WgerClient
from pete_e.utils.coercion import coerce_decimal_to_float


@dataclass(frozen=True)
class WeeklyAutomationResult:
    calibration: WeeklyCalibrationResult
    rollover: CycleRolloverResult | None
    rollover_triggered: bool
    """Represent WeeklyAutomationResult."""


@dataclass(frozen=True)
class _DailySummaryDraft:
    target: date
    action_date: date
    fallback_message: str
    metrics_payload: Dict[str, Any]
    guidance: str | None = None
    nutrition_line: str | None = None
    supplemental_lines: tuple[str, ...] = ()


def _build_metrics_overview_payload(
    *, columns: Sequence[str], rows: Iterable[Sequence[Any]], reference_date: date
) -> Dict[str, Any]:
    metrics: Dict[str, Dict[str, Any]] = {}
    for raw_row in rows or []:
        entry = {str(column): coerce_decimal_to_float(raw_row[idx]) for idx, column in enumerate(columns)}
        metric_name = entry.get("metric_name")
        if not metric_name:
            continue
        metrics[str(metric_name)] = entry

    return {
        "reference_date": reference_date,
        "metrics": metrics,
    }
    """Perform build metrics overview payload."""


class Orchestrator:
    """Coordinates Pete-Eebot workflows by delegating to application services."""

    def __init__(
        self,
        *,
        container: Container | None = None,
        validation_service: ValidationContract | None = None,
        cycle_service: CycleContract | None = None,
        telegram_client: MessagingContract | None = None,
        narrative_builder: NarrativeBuilder | None = None,
        dal: DataAccessContract | None = None,
        plan_service: PlanGenerationContract | None = None,
        export_service: ExportContract | None = None,
        daily_sync_service: SyncContract | None = None,
        voice_service: CoachVoiceService | None = None,
    ):
        """Initialize orchestrator dependencies."""
        container = container or get_container()

        # Resolve shared dependencies
        self.dal = dal or container.resolve(PostgresDal)
        self.wger_client = container.resolve(WgerClient)
        self.plan_service = plan_service or container.resolve(PlanService)
        self.export_service = export_service or container.resolve(WgerExportService)
        self.daily_sync_service = daily_sync_service or container.resolve(DailySyncService)
        self.validation_service = validation_service or self._resolve_validation_service(container)
        self.cycle_service = cycle_service or self._resolve_cycle_service(container)

        try:
            self.telegram_client = telegram_client or container.resolve(TelegramClient)
        except KeyError:
            self.telegram_client = telegram_client
            if self.telegram_client is None:
                log_utils.warn(
                    "TelegramClient dependency is unavailable; Telegram sends will be disabled."
                )

        self.narrative_builder = narrative_builder or provide_narrative_builder()
        payload_recorder = getattr(self.dal, "record_coach_voice_payload", None)
        self.voice_service = voice_service or provide_coach_voice_service(
            payload_recorder=payload_recorder if callable(payload_recorder) else None
        )

        self.weekly_calibration_workflow = WeeklyCalibrationWorkflow(self.validation_service)
        self.cycle_rollover_workflow = CycleRolloverWorkflow(
            plan_service=self.plan_service,
            export_service=self.export_service,
            hold_plan_generation_lock=self._hold_plan_generation_lock,
        )
        self.daily_sync_workflow = DailySyncWorkflow(
            daily_sync_service=self.daily_sync_service,
            send_message=self.send_telegram_message,
        )
        self.trainer_message_workflow = TrainerMessageWorkflow(
            dal=self.dal,
            build_context=self._build_trainer_context,
        )

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


    def _resolve_validation_service(self, container: Container) -> ValidationContract:
        try:
            return container.resolve(ValidationService)
        except KeyError:
            return provide_validation_service(dal=self.dal)

    def _resolve_cycle_service(self, container: Container) -> CycleContract:
        try:
            return container.resolve(CycleService)
        except KeyError:
            return provide_cycle_service()

    def _hold_plan_generation_lock(self):
        holder = getattr(self.dal, "hold_plan_generation_lock", None)
        if callable(holder):
            return holder()
        return nullcontext()
        """Perform hold plan generation lock."""


    def run_weekly_calibration(self, reference_date: date) -> WeeklyCalibrationResult:
        """Runs validation and progression on the upcoming week."""
        return self.weekly_calibration_workflow.run(reference_date)

    def run_cycle_rollover(
        self,
        reference_date: date,
        *,
        validation_decision: ValidationDecision | None = None,
    ) -> CycleRolloverResult:
        """Handles end-of-cycle logic by delegating to the workflow module."""
        return self.cycle_rollover_workflow.run(
            reference_date,
            validation_decision=validation_decision,
        )

    def run_end_to_end_week(self, reference_date: date | None = None) -> WeeklyAutomationResult:
        """
        The main entry point for the Sunday review.
        """
        run_date = reference_date or date.today()
        review_anchor = self._resolve_review_anchor(run_date)
        if review_anchor != run_date:
            log_utils.info(
                f"Weekly automation invoked on {run_date.isoformat()} ({run_date.strftime('%A')}); "
                f"anchoring cadence checks to Sunday {review_anchor.isoformat()}."
            )

        # Run calibration on the upcoming week
        calibration_result = self.run_weekly_calibration(review_anchor)
        validation_decision = calibration_result.validation

        # Decide if a rollover is needed via the domain service
        rollover_result = None

        try:
            active_plan = self.dal.get_active_plan()
        except ApplicationError:
            raise
        except Exception as exc:  # pragma: no cover - defensive guard
            message = f"Failed to load active plan before weekly run on {run_date.isoformat()}: {exc}"
            log_utils.error(message, "ERROR")
            raise DataAccessError(message) from exc

        plan_snapshot = self._summarise_active_plan(active_plan, review_anchor)
        log_utils.info(f"Cycle rollover checkpoint: {plan_snapshot}")

        try:
            rollover_triggered = self.cycle_service.check_and_rollover(active_plan, review_anchor)
        except ApplicationError:
            raise
        except Exception as exc:  # pragma: no cover - defensive guard
            message = f"Failed to evaluate rollover for {review_anchor.isoformat()}: {exc}"
            log_utils.error(message, "ERROR")
            raise PlanRolloverError(message) from exc

        log_utils.info(
            f"Cycle rollover decision: triggered={rollover_triggered}, context={plan_snapshot}"
        )

        if rollover_triggered:
            rollover_result = self.run_cycle_rollover(
                review_anchor,
                validation_decision=validation_decision,
            )
        else:
            next_week_start = self._next_week_start(review_anchor)
            self._export_active_week(
                active_plan=active_plan,
                week_start=next_week_start,
                validation_decision=validation_decision,
            )

        return WeeklyAutomationResult(
            calibration=calibration_result,
            rollover=rollover_result,
            rollover_triggered=rollover_triggered
        )
        
    def run_daily_sync(self, days: int):
        """Orchestrates the daily sync of all data sources."""
        return self.daily_sync_workflow.run_daily_sync(days)

    def run_withings_only_sync(self, days: int):
        """Runs only the Withings portion of the sync and refreshes views."""
        result = self.daily_sync_service.run_withings_only(days=days)
        return result.as_tuple()

    def run_end_to_end_day(
        self,
        *,
        days: int = 1,
        summary_date: date | None = None,
    ) -> DailyAutomationResult:
        """Run the daily sync and, when appropriate, send the daily summary."""
        return self.daily_sync_workflow.run(
            days=days,
            summary_date=summary_date,
            orchestrator=self,
        )

    def generate_and_deploy_next_plan(self, start_date: date, weeks: int = 4) -> int:
        """Create the next 4-week plan block and export week one."""

        if weeks != 4:
            raise ValidationError("Only 4-week plan generation is currently supported.")

        log_utils.info(
            f"Generating and deploying the next plan block starting {start_date.isoformat()}."
        )

        with self._hold_plan_generation_lock():
            try:
                plan_id = self.plan_service.create_next_plan_for_cycle(start_date=start_date)
                self.export_service.export_plan_week(
                    plan_id=plan_id,
                    week_number=1,
                    start_date=start_date,
                    force_overwrite=True,
                )
            except ApplicationError:
                raise
            except Exception as exc:  # pragma: no cover - defensive guard
                message = (
                    f"Plan generation failed for start date {start_date.isoformat()}: {exc}"
                )
                log_utils.error(message, "ERROR")
                raise PlanRolloverError(message) from exc

        return plan_id

    def generate_strength_test_week(self, start_date: date | None = None) -> bool:
        """Create and export a one-week strength-test block."""

        if start_date is None:
            today = date.today()
            days_until_monday = (0 - today.weekday()) % 7
            start_date = today + timedelta(days=days_until_monday)

        log_utils.info(f"Generating strength test week starting {start_date.isoformat()}.")

        with self._hold_plan_generation_lock():
            try:
                plan_id = self.plan_service.create_and_persist_strength_test_week(start_date)
                self.export_service.export_plan_week(
                    plan_id=plan_id,
                    week_number=1,
                    start_date=start_date,
                    force_overwrite=True,
                )
            except ApplicationError:
                raise
            except Exception as exc:  # pragma: no cover - defensive guard
                message = (
                    f"Strength test week generation failed for {start_date.isoformat()}: {exc}"
                )
                log_utils.error(message, "ERROR")
                raise PlanRolloverError(message) from exc

        return True

    def close(self):
        """Closes any open connections, like the database pool."""
        self.dal.close()

    # ------------------------------------------------------------------
    # Messaging helpers
    # ------------------------------------------------------------------

    def get_daily_summary(self, target_date: date | None = None) -> str:
        """Return the deterministic morning narrative fallback for the chosen day."""

        return self._build_daily_summary_draft(target_date=target_date).fallback_message

    def build_daily_summary_message(self, target_date: date | None = None) -> str:
        """Return the Telegram-ready daily summary, using Ollama when enabled."""

        draft = self._build_daily_summary_draft(target_date=target_date)
        request = self._build_daily_voice_request(draft)
        composer = getattr(self.voice_service, "compose", None)
        if callable(composer):
            return composer(request, fallback_message=draft.fallback_message)
        return self.voice_service.rewrite(draft.fallback_message)

    def _build_daily_summary_draft(self, target_date: date | None = None) -> _DailySummaryDraft:
        """Build deterministic daily summary content and structured context."""

        target = target_date or (date.today() - timedelta(days=1))

        try:
            columns, rows = self.dal.get_metrics_overview(target)
        except ApplicationError:
            raise
        except Exception as exc:  # pragma: no cover - defensive guard
            message = f"Failed to load metrics overview for {target.isoformat()}: {exc}"
            log_utils.error(message)
            raise DataAccessError(message) from exc

        metrics_payload = _build_metrics_overview_payload(
            columns=columns or [],
            rows=rows or [],
            reference_date=target,
        )

        builder = self.narrative_builder or NarrativeBuilder()
        try:
            if hasattr(builder, "build_daily_narrative"):
                report = builder.build_daily_narrative(metrics_payload)
            else:
                report = build_daily_narrative(metrics=metrics_payload)
        except Exception as exc:  # pragma: no cover - defensive guard
            message = f"Failed to build daily narrative for {target.isoformat()}: {exc}"
            log_utils.error(message)
            raise ApplicationError(message) from exc

        action_date = date.today() if target_date is None else target
        guidance = self._build_morning_training_guidance(
            report_date=target,
            action_date=action_date,
        )
        nutrition_line = self._build_nutrition_summary_line(target)
        supplemental_lines = tuple(self._build_daily_supplemental_lines(target))

        combined = report.rstrip()
        if guidance:
            combined = f"{combined}\n\n{guidance}"
        if nutrition_line:
            combined = f"{combined}\n\n{nutrition_line}"
        for line in supplemental_lines:
            combined = self._append_line(combined, line)

        return _DailySummaryDraft(
            target=target,
            action_date=action_date,
            fallback_message=combined,
            metrics_payload=metrics_payload,
            guidance=guidance,
            nutrition_line=nutrition_line,
            supplemental_lines=supplemental_lines,
        )

    def _build_daily_voice_request(self, draft: _DailySummaryDraft) -> CoachVoiceRequest:
        coach_state = self._load_coach_state_context(draft.target)
        profile = coach_state.get("profile") if isinstance(coach_state, dict) else {}
        if not isinstance(profile, dict):
            profile = {}

        facts: list[CoachVoiceFact] = []
        if draft.guidance:
            facts.append(
                CoachVoiceFact(
                    id="training_guidance",
                    text=draft.guidance,
                    source="morning_training_adjustment",
                    required=True,
                )
            )
        if draft.nutrition_line:
            facts.append(
                CoachVoiceFact(
                    id="nutrition_summary",
                    text=draft.nutrition_line,
                    source="nutrition_log",
                    confidence="estimated",
                    required=False,
                )
            )
        for idx, line in enumerate(draft.supplemental_lines, start=1):
            facts.append(
                CoachVoiceFact(
                    id=f"supplemental_context_{idx}",
                    text=line,
                    source="daily_summary_context",
                    required=False,
                )
            )

        return CoachVoiceRequest(
            message_type="daily_summary",
            intent="morning coaching check-in",
            audience={
                "name": profile.get("display_name") or "Ric",
                "timezone": profile.get("timezone") or "Europe/London",
            },
            dates={
                "report_date": draft.target.isoformat(),
                "action_date": draft.action_date.isoformat(),
            },
            metrics_report=draft.metrics_payload,
            coach_state=coach_state,
            goals=coach_state.get("goal_state", {}) if isinstance(coach_state, dict) else {},
            recent_context={
                "plan_context": coach_state.get("plan_context", {}) if isinstance(coach_state, dict) else {},
                "recent_workouts": coach_state.get("recent_workouts", {}) if isinstance(coach_state, dict) else {},
                "nutrition": coach_state.get("nutrition", {}) if isinstance(coach_state, dict) else {},
                "supplemental_lines": list(draft.supplemental_lines),
            },
            deterministic_decisions={
                "readiness_state": (
                    coach_state.get("summary", {}).get("readiness_state")
                    if isinstance(coach_state.get("summary"), dict)
                    else None
                )
                if isinstance(coach_state, dict)
                else None,
                "morning_training_guidance": draft.guidance,
            },
            constraints_and_warnings=list(
                coach_state.get("coaching_notes", []) if isinstance(coach_state, dict) else []
            ),
            must_include_facts=facts,
            style={
                "channel": "telegram",
                "voice": "Pete",
                "tone": "personal, direct, natural, encouraging",
                "max_words": 180,
                "format": "short text message with compact paragraphs or bullets",
            },
        )

    def _load_coach_state_context(self, target: date) -> Dict[str, Any]:
        try:
            from pete_e.application.api_services import MetricsService

            return MetricsService(self.dal).coach_state(target.isoformat())
        except Exception as exc:  # pragma: no cover - context should not block fallback
            log_utils.warn(f"Failed to load structured coach state for voice context: {exc}")
            return {}


    def _build_nutrition_summary_line(self, target_date: date) -> str | None:
        loader = getattr(self.dal, "get_nutrition_daily_summary", None)
        if not callable(loader):
            return None

        try:
            summary = loader(target_date) or {}
        except Exception as exc:  # pragma: no cover - defensive guard
            log_utils.warn(f"Failed to load nutrition summary for {target_date.isoformat()}: {exc}")
            return None

        meals = int(summary.get("meals_logged") or 0)
        if meals <= 0:
            return None

        calories = coerce_decimal_to_float(summary.get("calories_est"))
        protein = coerce_decimal_to_float(summary.get("protein_g"))
        carbs = coerce_decimal_to_float(summary.get("carbs_g"))
        fat = coerce_decimal_to_float(summary.get("fat_g"))

        if None in (calories, protein, carbs, fat):
            return None

        return (
            "Yesterday you logged "
            f"{calories:.0f} kcal with macros at {protein:.0f}g protein, "
            f"{carbs:.0f}g carbs, and {fat:.0f}g fat."
        )

    def _build_daily_supplemental_lines(self, target: date) -> List[str]:
        lines: list[str] = []
        body_age_line = self._format_body_age_line(target)
        if body_age_line:
            lines.append(body_age_line)
        body_comp_line = self._format_body_comp_line(target)
        if body_comp_line:
            lines.append(body_comp_line)
        hrv_line = self._format_hrv_line(target)
        if hrv_line:
            lines.append(hrv_line)
        trend_line = self._build_trend_paragraph(target)
        if trend_line:
            lines.append(trend_line)
        return lines

    def _format_body_age_line(self, target: date) -> str | None:
        try:
            trend = body_age.get_body_age_trend(getattr(self, "dal", None), target_date=target)
        except Exception as exc:  # pragma: no cover - defensive context only
            log_utils.warn(f"Failed to load body age trend for voice context: {exc}")
            return None
        if trend is None:
            return None
        value = getattr(trend, "value", None)
        delta = getattr(trend, "delta", None)
        if value is None:
            return None
        line = f"Body Age: {value:.1f}y"
        if delta is None:
            return f"{line} (7d delta n/a)"
        return f"{line} (7d delta {delta:+.1f}y)"

    def _format_body_comp_line(self, target: date) -> str | None:
        dal = getattr(self, "dal", None)
        loader = getattr(dal, "get_historical_metrics", None) if dal is not None else None
        if not callable(loader):
            return None
        try:
            rows = loader(14)
        except Exception as exc:  # pragma: no cover - defensive context only
            log_utils.warn(f"Failed to load body composition history for voice context: {exc}")
            return None

        window_start = target - timedelta(days=13)
        current_start = target - timedelta(days=6)
        samples: list[tuple[date, float]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            row_date = self._coerce_date(row.get("date"))
            if row_date is None or row_date > target or row_date < window_start:
                continue
            muscle_pct = coerce_decimal_to_float(row.get("muscle_pct"))
            if muscle_pct is not None:
                samples.append((row_date, muscle_pct))

        if not samples:
            return None
        samples.sort(key=lambda item: item[0])
        current_values = [value for sample_date, value in samples if current_start <= sample_date <= target]
        previous_values = [value for sample_date, value in samples if window_start <= sample_date < current_start]
        if len(current_values) < 3:
            return None
        avg_current = round(sum(current_values) / len(current_values), 1)
        if len(previous_values) >= 3:
            avg_previous = round(sum(previous_values) / len(previous_values), 1)
            diff = round(avg_current - avg_previous, 1)
            if abs(diff) >= 0.5:
                direction = "up" if diff > 0 else "down"
                return f"Muscle trend: {avg_current:.1f}% avg this week ({direction} {abs(diff):.1f}% vs prior)."
            return f"Muscle trend: {avg_current:.1f}% avg this week (steady vs prior)."
        return f"Muscle trend: {avg_current:.1f}% avg this week."

    def _format_hrv_line(self, target: date) -> str | None:
        dal = getattr(self, "dal", None)
        loader = getattr(dal, "get_historical_metrics", None) if dal is not None else None
        if not callable(loader):
            return None
        try:
            rows = loader(14)
        except Exception as exc:  # pragma: no cover - defensive context only
            log_utils.warn(f"Failed to load HRV history for voice context: {exc}")
            return None

        window_start = target - timedelta(days=6)
        samples: list[tuple[date, float]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            row_date = self._coerce_date(row.get("date"))
            if row_date is None or row_date < window_start or row_date > target:
                continue
            hrv_value = None
            for key in ("hrv_sdnn_ms", "hrv_rmssd_ms", "hrv_daily_ms", "hrv"):
                hrv_value = coerce_decimal_to_float(row.get(key))
                if hrv_value is not None:
                    break
            if hrv_value is not None and hrv_value > 0:
                samples.append((row_date, hrv_value))

        if not samples:
            return None
        samples.sort(key=lambda item: item[0])
        current_date = target
        current_value = next((value for sample_date, value in samples if sample_date == target), None)
        if current_value is None:
            current_date, current_value = samples[-1]
        previous_values = [value for sample_date, value in samples if sample_date < current_date]
        avg_previous = sum(previous_values) / len(previous_values) if previous_values else None
        direction = "steady"
        if avg_previous is not None:
            delta = current_value - avg_previous
            if delta >= 2.0:
                direction = "up"
            elif delta <= -2.0:
                direction = "down"
        line = f"HRV: {current_value:.0f} ms ({direction})"
        if avg_previous is not None:
            line += f" vs 7d avg {avg_previous:.0f} ms"
        return line

    def _build_trend_paragraph(self, target: date) -> str | None:
        samples = self._collect_trend_samples(target)
        if not samples:
            return None
        lines = narrative_builder.compute_trend_lines(samples, as_of=target, limit=2)
        if not lines:
            return None
        sentences = ["Trend check: " + lines[0]] + lines[1:]
        return " ".join(sentences)

    def _collect_trend_samples(self, target: date) -> list[tuple[date, dict]]:
        dal = getattr(self, "dal", None)
        loader = getattr(dal, "get_historical_data", None) if dal is not None else None
        if not callable(loader):
            return []
        start = target - timedelta(days=89)
        try:
            rows = loader(start, target)
        except Exception as exc:  # pragma: no cover - defensive context only
            log_utils.warn(f"Failed to load trend history for voice context: {exc}")
            return []
        samples: list[tuple[date, dict]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            row_date = self._coerce_date(row.get("date"))
            if row_date is None or row_date > target:
                continue
            samples.append((row_date, row))
        samples.sort(key=lambda item: item[0])
        return samples

    @staticmethod
    def _append_line(base: str | None, addition: str) -> str:
        base_text = "" if base is None else str(base)
        if not addition:
            return base_text
        if not base_text:
            return addition
        if not base_text.endswith("\n"):
            base_text = f"{base_text}\n"
        return f"{base_text}{addition}"

    def build_trainer_message(self, message_date: date | None = None) -> str:
        """Compose Pierre's trainer check-in for the supplied date."""
        trainer_context = self.trainer_message_workflow.build_message_context(message_date)
        coach_state = self._load_coach_state_context(trainer_context.target)
        profile = coach_state.get("profile") if isinstance(coach_state, dict) else {}
        if not isinstance(profile, dict):
            profile = {}
        session_type = trainer_context.context.get("today_session_type")
        facts: list[CoachVoiceFact] = []
        if session_type:
            facts.append(
                CoachVoiceFact(
                    id="today_session",
                    text=f"Today's session context: {session_type}",
                    source="training_plan",
                    required=True,
                )
            )

        request = CoachVoiceRequest(
            message_type="trainer_summary",
            intent="trainer-style daily check-in",
            audience={
                "name": profile.get("display_name") or trainer_context.context.get("user_name") or "Ric",
                "timezone": profile.get("timezone") or "Europe/London",
            },
            dates={
                "message_date": trainer_context.target.isoformat(),
            },
            metrics_report={
                "reference_date": trainer_context.target.isoformat(),
                "metrics": trainer_context.metrics,
            },
            coach_state=coach_state,
            goals=coach_state.get("goal_state", {}) if isinstance(coach_state, dict) else {},
            recent_context={
                "trainer_context": trainer_context.context,
                "plan_context": coach_state.get("plan_context", {}) if isinstance(coach_state, dict) else {},
                "recent_workouts": coach_state.get("recent_workouts", {}) if isinstance(coach_state, dict) else {},
            },
            deterministic_decisions={
                "session_context": session_type,
                "readiness_state": (
                    coach_state.get("summary", {}).get("readiness_state")
                    if isinstance(coach_state.get("summary"), dict)
                    else None
                )
                if isinstance(coach_state, dict)
                else None,
            },
            constraints_and_warnings=list(
                coach_state.get("coaching_notes", []) if isinstance(coach_state, dict) else []
            ),
            must_include_facts=facts,
            style={
                "channel": "telegram",
                "voice": "Pierre",
                "tone": "direct trainer, light franglais, natural, personal",
                "max_words": 180,
                "format": "short text message with compact paragraphs",
            },
        )
        composer = getattr(self.voice_service, "compose", None)
        if callable(composer):
            return composer(request, fallback_message=trainer_context.fallback_message)
        return self.voice_service.rewrite(trainer_context.fallback_message)

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

    def _build_morning_training_guidance(
        self,
        *,
        report_date: date,
        action_date: date,
    ) -> str | None:
        """Return session-specific coaching advice for the morning report."""

        dal = getattr(self, "dal", None)
        if dal is None:
            return None

        try:
            history_loader = getattr(dal, "get_historical_data", None)
            if not callable(history_loader):
                return None
            history_start = action_date - timedelta(days=180)
            history_end = min(report_date, action_date - timedelta(days=1))
            historical_rows = history_loader(history_start, history_end)
        except Exception as exc:  # pragma: no cover - defensive guard
            log_utils.warn(f"Failed to load running readiness history: {exc}")
            return None

        try:
            run_loader = getattr(dal, "get_recent_running_workouts", None)
            recent_runs = (
                run_loader(days=90, end_date=history_end)
                if callable(run_loader)
                else []
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            log_utils.warn(f"Failed to load recent running workouts: {exc}")
            recent_runs = []

        export_context = self._resolve_daily_export_context(action_date)
        plan_rows = self._load_daily_plan_rows(action_date, export_context=export_context)

        adjustment = build_morning_training_adjustment(
            health_metrics=historical_rows,
            recent_runs=recent_runs,
            action_date=action_date,
            plan_rows=plan_rows,
        )
        if adjustment is None or not adjustment.message:
            return None

        message = adjustment.message
        if adjustment.should_adjust and adjustment.wger_adjustment is not None:
            status = self._export_daily_wger_adjustment(
                export_context=export_context,
                adjustment=adjustment,
            )
            if status == "updated":
                message = f"{message}\n\nI've sent the updates to Wger for you."
            elif status == "unavailable":
                message = f"{message} Wger update unavailable; apply this manually today."
            else:
                message = f"{message} Wger update failed; apply this manually today."
        return message

    def _load_daily_plan_rows(
        self,
        action_date: date,
        *,
        export_context: Dict[str, Any] | None,
    ) -> List[Dict[str, Any]]:
        """Load rich plan rows for today, falling back to the lightweight day view."""

        if export_context is not None:
            loader = getattr(self.dal, "get_plan_week_rows", None)
            if callable(loader):
                try:
                    rows = list(
                        loader(
                            export_context["plan_id"],
                            export_context["week_number"],
                        )
                        or []
                    )
                except Exception as exc:  # pragma: no cover - defensive guard
                    log_utils.warn(f"Failed to load rich plan rows for morning coaching: {exc}")
                else:
                    day_number = action_date.isoweekday()
                    day_rows = [
                        row
                        for row in rows
                        if self._coerce_positive_int(row.get("day_of_week")) == day_number
                    ]
                    if day_rows:
                        return day_rows

        return list(self._load_plan_for_day(action_date))

    def _resolve_daily_export_context(self, action_date: date) -> Dict[str, Any] | None:
        """Resolve active plan details needed to refresh the current wger week."""

        loader = getattr(self.dal, "get_active_plan", None)
        if not callable(loader):
            return None
        try:
            active_plan = loader()
        except Exception as exc:  # pragma: no cover - defensive guard
            log_utils.warn(f"Failed to resolve active plan for morning coaching: {exc}")
            return None
        if not active_plan:
            return None

        plan_id = active_plan.get("id") or active_plan.get("plan_id")
        plan_start = self._coerce_date(active_plan.get("start_date"))
        if not plan_id or plan_start is None:
            return None

        week_number = self._plan_week_index(plan_start, action_date)
        if week_number is None:
            return None
        plan_weeks = self._coerce_positive_int(active_plan.get("weeks"))
        if plan_weeks is not None and week_number > plan_weeks:
            return None

        return {
            "plan_id": int(plan_id),
            "week_number": week_number,
            "week_start": plan_start + timedelta(days=(week_number - 1) * 7),
        }

    def _export_daily_wger_adjustment(
        self,
        *,
        export_context: Dict[str, Any] | None,
        adjustment: Any,
    ) -> str:
        """Push today's scoped readiness adjustment into the current wger week."""

        if export_context is None:
            return "unavailable"
        wger_adjustment = getattr(adjustment, "wger_adjustment", None)
        validation_decision = getattr(adjustment, "validation_decision", None)
        if wger_adjustment is None or validation_decision is None:
            return "unavailable"

        try:
            self.export_service.export_plan_week(
                plan_id=export_context["plan_id"],
                week_number=export_context["week_number"],
                start_date=export_context["week_start"],
                force_overwrite=True,
                validation_decision=validation_decision,
                daily_adjustment=wger_adjustment,
            )
        except TypeError as exc:
            log_utils.warn(
                "Morning Wger update could not be applied because the export service "
                f"does not support daily adjustments: {exc}"
            )
            return "unavailable"
        except Exception as exc:  # pragma: no cover - external API guard
            log_utils.warn(f"Morning Wger update failed: {exc}")
            return "failed"
        return "updated"

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
        """Fetch normalized plan context rows for the given day."""

        dal = getattr(self, "dal", None)
        if dal is None or not hasattr(dal, "get_plan_for_day"):
            return []

        try:
            return PlanReadModel(dal).load_day_context(target)
        except Exception as exc:  # pragma: no cover - defensive guard
            log_utils.warn(f"Failed to load plan for {target.isoformat()}: {exc}")
            return []

    @staticmethod
    def _extract_running_plan_names(plan_rows: Iterable[Dict[str, Any]]) -> List[str]:
        """Return unique plan exercise names that look like running sessions."""

        run_tokens = (
            "run",
            "jog",
            "interval",
            "tempo",
            "fartlek",
            "sprint",
            "hill",
            "track",
            "5k",
            "10k",
            "marathon",
        )
        names: List[str] = []
        for row in plan_rows:
            raw_name = row.get("exercise_name")
            if not raw_name:
                continue
            label = str(raw_name).strip()
            if not label:
                continue
            lowered = label.lower()
            if not any(token in lowered for token in run_tokens):
                continue
            if label in names:
                continue
            names.append(label)
        return names

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

    @staticmethod
    def _resolve_review_anchor(reference_date: date) -> date:
        """Normalize the weekly automation anchor to the most recent Sunday."""

        if reference_date.weekday() == 6:
            return reference_date

        days_since_sunday = (reference_date.weekday() - 6) % 7
        return reference_date - timedelta(days=days_since_sunday)

    @staticmethod
    def _next_week_start(reference_date: date) -> date:
        """Return the Monday immediately after the supplied anchor date."""

        days_until_monday = (0 - reference_date.weekday()) % 7
        candidate = reference_date + timedelta(days=days_until_monday)
        if candidate <= reference_date:
            candidate += timedelta(days=7)
        return candidate

    @staticmethod
    def _resolve_export_week_number(
        *,
        calculated_week_number: int,
        validation_decision: ValidationDecision | None,
    ) -> int:
        """Determine whether the athlete should advance or repeat the prior week."""

        if calculated_week_number <= 1 or validation_decision is None:
            return calculated_week_number

        metrics = getattr(validation_decision, "recommendation", None)
        recommendation_metrics = getattr(metrics, "metrics", {}) if metrics is not None else {}
        adherence_metrics = (
            recommendation_metrics.get("adherence", {})
            if isinstance(recommendation_metrics, dict)
            else {}
        )
        if not isinstance(adherence_metrics, dict):
            return calculated_week_number
        if not adherence_metrics.get("available"):
            return calculated_week_number

        try:
            adherence_ratio = float(adherence_metrics.get("ratio", 1.0))
        except (TypeError, ValueError):
            adherence_ratio = 1.0

        minimum_completion_ratio = 0.70
        if adherence_ratio >= minimum_completion_ratio:
            return calculated_week_number

        return max(1, calculated_week_number - 1)

    def _export_active_week(
        self,
        *,
        active_plan: Dict[str, Any] | None,
        week_start: date,
        validation_decision: ValidationDecision | None,
    ) -> None:
        """Push the upcoming training week to wger for the active plan."""

        if not active_plan:
            log_utils.warn(
                "Skipping weekly export because no active plan was available.",
                "WARN",
            )
            return

        plan_id = active_plan.get("id")
        plan_start = self._coerce_date(active_plan.get("start_date"))
        if not plan_id or plan_start is None:
            log_utils.warn(
                f"Cannot export weekly plan: invalid plan payload {active_plan}",
                "WARN",
            )
            return

        week_number = self._plan_week_index(plan_start, week_start)
        if week_number is None:
            log_utils.warn(
                f"Cannot export weekly plan: week_start {week_start.isoformat()} precedes plan start {plan_start.isoformat()}",
                "WARN",
            )
            return

        exported_week_number = self._resolve_export_week_number(
            calculated_week_number=week_number,
            validation_decision=validation_decision,
        )
        if exported_week_number != week_number:
            log_utils.info(
                f"Holding progression for plan {plan_id}: adherence below completion threshold; "
                f"re-exporting week {exported_week_number} into {week_start.isoformat()}."
            )

        plan_weeks = self._coerce_positive_int(active_plan.get("weeks"))
        if plan_weeks is not None and exported_week_number > plan_weeks:
            log_utils.warn(
                f"Skipping weekly export for plan {plan_id}: week {exported_week_number} exceeds plan length {plan_weeks}",
                "WARN",
            )
            return

        log_utils.info(
            f"Exporting plan {plan_id} week {exported_week_number} to wger for week starting {week_start.isoformat()}."
        )

        try:
            self.export_service.export_plan_week(
                plan_id=plan_id,
                week_number=exported_week_number,
                start_date=week_start,
                force_overwrite=True,
                validation_decision=validation_decision,
            )
        except ApplicationError:
            raise
        except Exception as exc:  # pragma: no cover - defensive guard
            message = (
                f"Weekly export failed for plan {plan_id} week {exported_week_number} starting {week_start.isoformat()}: {exc}"
            )
            log_utils.error(message, "ERROR")
            raise PlanRolloverError(message) from exc
        else:
            log_utils.info(
                f"Exported plan {plan_id} week {exported_week_number} to wger for {week_start.isoformat()}."
            )

    @staticmethod
    def _summarise_active_plan(active_plan: Dict[str, Any] | None, reference_date: date) -> Dict[str, Any]:
        """Collect lightweight debugging info for the weekly rollover checkpoint."""

        summary: Dict[str, Any] = {
            "reference_date": reference_date.isoformat(),
            "weekday": reference_date.strftime("%A"),
        }

        if not active_plan:
            summary["status"] = "no-active-plan"
            return summary

        start_date = Orchestrator._coerce_date(active_plan.get("start_date"))
        plan_weeks = Orchestrator._coerce_positive_int(active_plan.get("weeks"))
        week_in_plan = Orchestrator._plan_week_index(start_date, reference_date)

        summary.update(
            {
                "plan_id": active_plan.get("id"),
                "plan_start": start_date.isoformat() if start_date else active_plan.get("start_date"),
                "plan_weeks": plan_weeks,
                "week_in_plan": week_in_plan,
            }
        )

        if start_date:
            summary["days_into_plan"] = (reference_date - start_date).days

        if "is_test" in active_plan:
            summary["is_test"] = active_plan.get("is_test")
        if "plan_type" in active_plan:
            summary["plan_type"] = active_plan.get("plan_type")

        return summary

    @staticmethod
    def _plan_week_index(start_date: date | None, reference_date: date) -> int | None:
        """Return the 1-based week index for the supplied start and reference dates."""

        if start_date is None:
            return None

        delta_days = (reference_date - start_date).days
        if delta_days < 0:
            return None
        return (delta_days // 7) + 1

    @staticmethod
    def _coerce_date(value: Any) -> date | None:
        """Best-effort conversion of DAL payloads to ``date`` objects."""

        if isinstance(value, date):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _coerce_positive_int(value: Any) -> int | None:
        """Helper shared with plan snapshots to keep log payloads legible."""

        try:
            candidate = int(value)
        except (TypeError, ValueError):
            return None
        return candidate if candidate > 0 else None
