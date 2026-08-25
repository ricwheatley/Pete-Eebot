# pete_e/application/services.py
"""
Contains high-level services that orchestrate domain logic and infrastructure.
This layer is responsible for coordinating tasks like plan creation and export.
"""

from __future__ import annotations
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List
import json
import math

from pete_e.application.exceptions import ConflictError
from pete_e.application.validation_service import ValidationService
from pete_e.application.strength_test import StrengthTestService
from pete_e.domain.validation import ValidationDecision
from pete_e.domain.entities import Plan, Week
from pete_e.domain.morning_coach import DailyWgerAdjustment
from pete_e.domain.plan_factory import PlanFactory
from pete_e.domain.prescription_validation import (
    PrescriptionValidationError,
    calculate_target_weight,
    validate_plan_prescriptions,
    validate_training_maxes,
    validate_wger_payload_prescriptions,
)
from pete_e.domain.running_planner import RunningGoal
from pete_e.domain import schedule_rules
from pete_e.config import settings
from pete_e.infrastructure.mappers import PlanMapper, WgerPayloadMapper
from pete_e.infrastructure.postgres_dal import PostgresDal
from pete_e.infrastructure.wger_client import WgerClient
from pete_e.infrastructure import log_utils

class PlanService:
    """Service for creating and managing training plans."""

    def __init__(self, dal: PostgresDal):
        """Initializes the service with a data access layer."""
        self.dal = dal
        self.factory = PlanFactory(plan_repository=self.dal)
        self.plan_mapper = PlanMapper()
        self.strength_test_service = StrengthTestService(dal)

    def create_and_persist_531_block(self, start_date: date) -> int:
        """
        Creates and persists a new 4-week 5/3/1 block.
        Orchestrates fetching TMs, building the plan object, and saving it.
        """
        log_utils.info(f"Creating new 5/3/1 block starting {start_date.isoformat()}...")
        # 1. Get latest TMs from DAL
        tms = self.dal.get_latest_training_maxes()
        validate_training_maxes(tms)
        health_metrics = self._load_recent_health_metrics()
        recent_runs = self._load_recent_running_workouts(end_date=start_date - timedelta(days=1))
        running_goal = self._running_goal_from_settings()
        
        # 2. Use PlanFactory to build the plan dictionary
        plan_dict = self.factory.create_unified_531_block_plan(
            start_date,
            tms,
            running_goal=running_goal,
            health_metrics=health_metrics,
            recent_runs=recent_runs,
        )
        self._audit_planner_feature_flag_effects(plan_dict, start_date=start_date)
        plan_entity = self.plan_mapper.from_dict(plan_dict)
        validate_plan_prescriptions(plan_entity)
        payload = self.plan_mapper.to_persistence_payload(plan_entity)

        # 3. Persist the plan using the DAL
        # This will be a new method in the DAL to save a full plan object.
        plan_id = self.dal.save_full_plan(payload)
        log_utils.info(f"Successfully created and persisted plan_id: {plan_id}")
        return plan_id

    def _audit_planner_feature_flag_effects(self, plan_dict: Dict[str, Any], *, start_date: date) -> None:
        metadata = plan_dict.get("metadata") if isinstance(plan_dict, dict) else {}
        if not isinstance(metadata, dict):
            return
        overrides = metadata.get("planner_feature_flag_overrides")
        effects = metadata.get("planner_feature_flag_effects")
        if not overrides or not effects:
            return
        log_utils.log_checkpoint(
            checkpoint="planner_feature_flags",
            outcome="applied",
            correlation={
                "workflow": "plan_generation",
                "start_date": start_date.isoformat(),
            },
            summary={
                "flags": overrides,
                "effects": effects,
            },
            tag="AUDIT",
        )

    def _load_recent_health_metrics(self) -> List[Dict[str, Any]]:
        loader = getattr(self.dal, "get_historical_metrics", None)
        if not callable(loader):
            return []
        try:
            return list(loader(180) or [])
        except Exception as exc:  # pragma: no cover - environment specific
            log_utils.warn(f"Running planner could not load health metrics: {exc}")
            return []
        """Perform load recent health metrics."""

    def _load_recent_running_workouts(self, *, end_date: date) -> List[Dict[str, Any]]:
        loader = getattr(self.dal, "get_recent_running_workouts", None)
        if not callable(loader):
            return []
        try:
            return list(loader(days=180, end_date=end_date) or [])
        except Exception as exc:  # pragma: no cover - environment specific
            log_utils.warn(f"Running planner could not load recent run workouts: {exc}")
            return []
        """Perform load recent running workouts."""

    @staticmethod
    def _running_goal_from_settings() -> RunningGoal:
        return RunningGoal(
            target_race=getattr(settings, "RUNNING_TARGET_RACE", "marathon"),
            race_date=getattr(settings, "RUNNING_RACE_DATE", None),
            target_time=getattr(settings, "RUNNING_TARGET_TIME", None),
            weight_loss_target_kg=getattr(settings, "RUNNING_WEIGHT_LOSS_TARGET_KG", None),
        )
        """Perform running goal from settings."""

    def create_and_persist_strength_test_week(self, start_date: date) -> int:
        """Creates and persists a new 1-week strength test plan."""
        log_utils.info(f"Creating new strength test week starting {start_date.isoformat()}...")
        tms = self.dal.get_latest_training_maxes()
        validate_training_maxes(tms)
        health_metrics = self._load_recent_health_metrics()
        recent_runs = self._load_recent_running_workouts(end_date=start_date - timedelta(days=1))
        running_goal = self._running_goal_from_settings()
        plan_dict = self.factory.create_strength_test_plan(
            start_date,
            tms,
            running_goal=running_goal,
            health_metrics=health_metrics,
            recent_runs=recent_runs,
        )
        plan_entity = self.plan_mapper.from_dict(plan_dict)
        validate_plan_prescriptions(plan_entity)
        payload = self.plan_mapper.to_persistence_payload(plan_entity)
        plan_id = self.dal.save_full_plan(payload)
        log_utils.info(f"Successfully created and persisted strength test plan_id: {plan_id}")
        return plan_id

    def create_next_plan_for_cycle(self, *, start_date: date) -> int:
        """Create the next block in the macrocycle and persist it."""

        log_utils.info(
            "Creating next macrocycle block via PlanService.create_next_plan_for_cycle..."
        )
        evaluation = self.strength_test_service.evaluate_latest_test_week_and_update_tms()
        if evaluation is None:
            log_utils.info("Generating next block from the current stored training maxes.")
        elif evaluation.lifts_updated == 0:
            log_utils.info(
                "Latest strength test week has no completed AMRAP logs yet; using existing training maxes."
            )
        else:
            log_utils.info(
                "Applied "
                f"{evaluation.lifts_updated} training max update(s) from strength test plan "
                f"{evaluation.plan_id} before generating the next block."
            )
        return self.create_and_persist_531_block(start_date)

    def repair_missing_percentage_targets(
        self,
        *,
        plan_id: int,
        weeks: int,
        recalibrate_training_maxes: bool = True,
    ) -> Dict[str, Any]:
        """Repair missing percentage targets without regenerating a stored plan.

        The complete prospective plan is validated before the DAL receives a
        single bulk update, so an unrepairable row cannot leave a partial fix.
        """

        if plan_id < 1 or weeks < 1:
            raise PrescriptionValidationError(
                ["plan_id and weeks must both be positive integers"]
            )

        if recalibrate_training_maxes:
            self.strength_test_service.evaluate_latest_test_week_and_update_tms()

        training_maxes = self.dal.get_latest_training_maxes()
        validate_training_maxes(training_maxes)

        prospective_rows: List[Dict[str, Any]] = []
        updates: List[Dict[str, Any]] = []
        repaired_lifts: set[str] = set()

        for week_number in range(1, weeks + 1):
            for original in self.dal.get_plan_week_rows(plan_id, week_number):
                row = dict(original)
                prospective_rows.append(row)
                percent = row.get("percent_1rm")
                if percent is None or bool(row.get("is_cardio")):
                    continue

                try:
                    current_target = float(row.get("target_weight_kg"))
                except (TypeError, ValueError):
                    current_target = 0.0
                if math.isfinite(current_target) and current_target > 0:
                    continue

                try:
                    exercise_id = int(row["exercise_id"])
                    workout_id = int(row["id"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise PrescriptionValidationError(
                        [
                            f"week {week_number}: percentage row is missing a valid "
                            "exercise or workout id"
                        ]
                    ) from exc

                lift_code = schedule_rules.LIFT_CODE_BY_ID.get(exercise_id)
                if lift_code is None:
                    raise PrescriptionValidationError(
                        [
                            f"week {week_number}, workout {workout_id}: cannot map "
                            f"exercise {exercise_id} to a training max"
                        ]
                    )

                target = calculate_target_weight(training_maxes[lift_code], percent)
                row["target_weight_kg"] = target
                updates.append(
                    {"workout_id": workout_id, "target_weight_kg": target}
                )
                repaired_lifts.add(lift_code)

        prospective_plan = self.plan_mapper.from_rows(
            {"start_date": None},
            prospective_rows,
        )
        validate_plan_prescriptions(prospective_plan)
        self.dal.update_workout_targets(updates)

        result = {
            "plan_id": plan_id,
            "weeks_checked": weeks,
            "workouts_updated": len(updates),
            "lifts_repaired": sorted(repaired_lifts),
        }
        log_utils.log_checkpoint(
            checkpoint="plan_target_repair",
            outcome="completed",
            correlation={"workflow": "plan_repair", "plan_id": plan_id},
            summary=result,
            tag="AUDIT",
        )
        return result


class WgerExportService:
    """Service for validating plans and exporting them to wger."""

    def __init__(
        self,
        dal: PostgresDal,
        wger_client: WgerClient,
        validation_service: ValidationService | None = None,
        plan_mapper: PlanMapper | None = None,
        payload_mapper: WgerPayloadMapper | None = None,
    ):
        self.dal = dal
        self.client = wger_client
        self.validation_service = validation_service or ValidationService(dal)
        self.plan_mapper = plan_mapper or PlanMapper()
        self.payload_mapper = payload_mapper or WgerPayloadMapper()
        """Initialize this object."""

    def export_plan_week(
        self,
        plan_id: int,
        week_number: int,
        start_date: date,
        force_overwrite: bool = False,
        dry_run: bool = False,
        validation_decision: ValidationDecision | None = None,
        daily_adjustment: DailyWgerAdjustment | None = None,
    ) -> Dict[str, Any]:
        """
        Validates, prepares, and pushes a single training week to wger.
        (Logic migrated from wger_sender.py and wger_exporter.py)
        """
        log_utils.info(f"Starting export for plan {plan_id}, week {week_number}...")
        correlation = {
            "workflow": "wger_export",
            "plan_id": plan_id,
            "week_number": week_number,
            "start_date": start_date.isoformat(),
        }
        log_utils.log_checkpoint(
            checkpoint="export",
            outcome="started",
            correlation=correlation,
            summary={"force_overwrite": force_overwrite, "dry_run": dry_run},
        )

        # A normal retry must not run unrelated readiness work once export state
        # already says there is nothing to send.
        if not force_overwrite and self.dal.was_week_exported(plan_id, week_number):
            log_utils.warn(f"Skipping export: plan {plan_id}, week {week_number} already exported.")
            log_utils.log_checkpoint(
                checkpoint="export",
                outcome="skipped",
                correlation=correlation,
                summary={"reason": "already-exported"},
            )
            return {"status": "skipped", "reason": "already-exported"}

        # Refuse malformed stored prescriptions before readiness can mutate the
        # database or any remote Wger resource can be touched.
        initial_rows = self.dal.get_plan_week_rows(plan_id, week_number)
        initial_normalized_rows = self._normalize_week_rows(
            initial_rows,
            week_number=week_number,
        )
        initial_payload = self._assemble_payload(
            plan_id=plan_id,
            week_number=week_number,
            rows=initial_normalized_rows,
            plan_start_date=start_date,
        )
        validate_wger_payload_prescriptions(initial_payload)

        # Force overwrite means reassess idempotently and resend to wger. It does
        # not mean applying another delta to the effective prescription.
        if validation_decision is None:
            assess = getattr(self.validation_service, "assess_plan", None)
            apply = getattr(self.validation_service, "apply_adjustment", None)
            if callable(assess):
                decision = assess(start_date)
                if not dry_run and callable(apply):
                    decision = apply(
                        decision,
                        plan_id=plan_id,
                        week_number=week_number,
                        week_start=start_date,
                    )
            else:  # Compatibility for application-owned adapter/test ports.
                decision = self.validation_service.validate_and_adjust_plan(start_date)
            log_utils.info(f"Readiness check: {decision.explanation}")
        else:
            decision = validation_decision
            apply = getattr(self.validation_service, "apply_adjustment", None)
            has_durable_identity = bool(getattr(decision, "source_data_hash", ""))
            targets_exported_week = (
                getattr(decision, "plan_id", None) == plan_id
                and getattr(decision, "week_number", None) == week_number
            )
            if (
                not dry_run
                and callable(apply)
                and has_durable_identity
                and (not getattr(decision, "applied", False) or not targets_exported_week)
            ):
                decision = apply(
                    decision,
                    plan_id=plan_id,
                    week_number=week_number,
                    week_start=start_date,
                )
        
        # Build the payload from the effective plan values in the DB.
        week_rows = self.dal.get_plan_week_rows(plan_id, week_number)
        normalized_rows = self._normalize_week_rows(week_rows, week_number=week_number)
        payload = self._assemble_payload(
            plan_id=plan_id,
            week_number=week_number,
            rows=normalized_rows,
            plan_start_date=start_date,
        )
        daily_changes = self._annotate_and_enrich_payload(
            payload=payload,
            plan_id=plan_id,
            week_number=week_number,
            rows=normalized_rows,
            decision=decision,
            daily_adjustment=daily_adjustment,
        )

        validate_wger_payload_prescriptions(payload)
        if daily_adjustment is not None and daily_changes == 0:
            log_utils.warn(
                "Skipping morning Wger update because today's prescription has "
                "no adjustable values."
            )
            log_utils.log_checkpoint(
                checkpoint="export",
                outcome="skipped",
                correlation=correlation,
                summary={"reason": "no-adjustable-values"},
            )
            return {"status": "skipped", "reason": "no-adjustable-values"}

        if dry_run:
            log_utils.info(f"[DRY RUN] Would export payload: {json.dumps(payload, indent=2)}")
            log_utils.log_checkpoint(
                checkpoint="export",
                outcome="dry_run",
                correlation=correlation,
                summary={"payload_days": len(payload.get("days", []))},
            )
            return {"status": "dry-run", "payload": payload}

        # 4. Resolve export IDs and submit payload via staged API pipeline
        self._resolve_export_ids(payload)
        routine_id, api_trace = self._submit_payload_to_api(
            payload=payload,
            start_date=start_date,
            force_overwrite=force_overwrite,
        )

        created_days = len(api_trace)
        created_slots = sum(len(day.get("slots", [])) for day in api_trace)
        created_entries = sum(
            1
            for day in api_trace
            for slot in day.get("slots", [])
            if slot.get("entry_id") is not None
        )

        # 5. Log the export result
        self.dal.record_wger_export(
            plan_id,
            week_number,
            payload,
            response={"routine_id": routine_id, "days": api_trace},
            routine_id=routine_id,
        )
        log_utils.info(
            "Successfully exported plan "
            f"{plan_id}, week {week_number} to wger routine {routine_id} "
            f"on {getattr(self.client, 'base_url', 'unknown-host')} "
            f"(days={created_days}, slots={created_slots}, slot_entries={created_entries})."
        )
        log_utils.log_checkpoint(
            checkpoint="export",
            outcome="completed",
            correlation={**correlation, "routine_id": routine_id},
            summary={"days": created_days, "slots": created_slots, "slot_entries": created_entries},
        )
        return {"status": "exported", "routine_id": routine_id}

    def replace_stored_plan_week(
        self,
        *,
        plan_id: int,
        week_number: int,
        start_date: date,
    ) -> Dict[str, Any]:
        """Delete a matching wger week if present and resend stored plan rows.

        This repair path deliberately bypasses readiness assessment and every
        plan-writing service. The effective rows already stored for the week
        are the sole source for the replacement payload.
        """

        correlation = {
            "workflow": "wger_week_replace",
            "plan_id": plan_id,
            "week_number": week_number,
            "start_date": start_date.isoformat(),
        }
        log_utils.log_checkpoint(
            checkpoint="replace",
            outcome="started",
            correlation=correlation,
            summary={"source": "stored_plan_rows"},
        )

        week_rows = self.dal.get_plan_week_rows(plan_id, week_number)
        if not week_rows:
            raise ConflictError(
                (
                    f"Stored plan {plan_id} week {week_number} has no workout rows; "
                    "refusing to delete anything in wger."
                ),
                code="empty_stored_plan_week",
            )

        normalized_rows = self._normalize_week_rows(week_rows, week_number=week_number)
        payload = self._assemble_payload(
            plan_id=plan_id,
            week_number=week_number,
            rows=normalized_rows,
            plan_start_date=start_date,
        )
        self._annotate_and_enrich_payload(
            payload=payload,
            plan_id=plan_id,
            week_number=week_number,
            rows=normalized_rows,
            decision=None,
            daily_adjustment=None,
        )
        validate_wger_payload_prescriptions(payload)
        self._resolve_export_ids(payload)

        routine_id, api_trace, replaced_existing = self._replace_payload_in_api(
            payload=payload,
            start_date=start_date,
        )
        self.dal.record_wger_export(
            plan_id,
            week_number,
            payload,
            response={
                "routine_id": routine_id,
                "days": api_trace,
                "replacement": True,
                "deleted_existing": replaced_existing,
            },
            routine_id=routine_id,
        )
        log_utils.log_checkpoint(
            checkpoint="replace",
            outcome="completed",
            correlation={**correlation, "routine_id": routine_id},
            summary={
                "days": len(api_trace),
                "deleted_existing": replaced_existing,
                "source": "stored_plan_rows",
            },
        )
        return {
            "status": "replaced" if replaced_existing else "exported",
            "routine_id": routine_id,
            "deleted_existing": replaced_existing,
            "days": len(api_trace),
        }

    @staticmethod
    def _fallback_routine_name(base_name: str) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return f"{base_name} retry {stamp}"
        """Perform fallback routine name."""

    @staticmethod
    def _staging_routine_name(base_name: str) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        return f"{base_name} staging {stamp}"

    def _apply_running_backoff_to_payload(
        self,
        payload: Dict[str, Any],
        decision: ValidationDecision | None,
        *,
        only_day_of_week: int | None = None,
    ) -> int:
        """Downgrade run intensity in the exported week when readiness is poor."""

        if decision is None or not decision.needs_backoff:
            return 0

        changes = 0

        readiness = getattr(decision, "readiness", None)
        severity = str(getattr(readiness, "severity", "") or "mild").lower()
        if severity not in {"mild", "moderate", "severe"}:
            severity = "mild"

        for day in payload.get("days", []):
            if only_day_of_week is not None:
                try:
                    day_of_week = int(day.get("day_of_week"))
                except (TypeError, ValueError):
                    day_of_week = None
                if day_of_week != only_day_of_week:
                    continue

            for entry in day.get("exercises", []):
                details = entry.get("details")
                if not isinstance(details, dict):
                    continue
                session_type = str(details.get("session_type") or "").strip().lower()
                if session_type not in schedule_rules.RUN_SESSION_TYPES:
                    continue

                original_comment = str(entry.get("comment") or "Run").strip()
                if session_type in {"intervals", "tempo", "steady"}:
                    duration = 20 if severity in {"moderate", "severe"} else 25
                    replacement = schedule_rules.easy_run_details(
                        duration_minutes=duration,
                        speed_kph=8.0,
                        min_speed_kph=7.8,
                        max_speed_kph=8.2,
                    )
                    entry["details"] = replacement
                    entry["comment"] = (
                        f"{original_comment} - backed off for recovery: "
                        f"{duration} min easy only."
                    )
                    entry["entry_comment"] = entry["comment"]
                    entry["recovery_focused"] = True
                    changes += 1
                    continue

                if session_type in {"easy", "recovery"} and severity in {"moderate", "severe"}:
                    duration = 20 if severity == "severe" else 25
                    replacement = schedule_rules.easy_run_details(
                        duration_minutes=duration,
                        speed_kph=7.8,
                        min_speed_kph=7.5,
                        max_speed_kph=8.0,
                    )
                    entry["details"] = replacement
                    entry["comment"] = (
                        f"{original_comment} - capped for recovery: "
                        f"{duration} min easy only."
                    )
                    entry["entry_comment"] = entry["comment"]
                    entry["recovery_focused"] = True
                    changes += 1
                    continue

                if session_type == "long_run" and severity in {"moderate", "severe"}:
                    steps = details.get("steps")
                    first = steps[0] if isinstance(steps, list) and steps and isinstance(steps[0], dict) else {}
                    try:
                        distance = float(first.get("distance_km") or 0)
                    except (TypeError, ValueError):
                        distance = 0.0
                    capped = max(4, round(distance * (0.70 if severity == "severe" else 0.80)))
                    replacement = schedule_rules.long_run_details(
                        distance_km=capped,
                        speed_kph=8.0,
                        min_speed_kph=7.8,
                        max_speed_kph=8.2,
                    )
                    entry["details"] = replacement
                    entry["comment"] = (
                        f"{original_comment} - backed off for recovery: "
                        f"cap at {capped} km easy."
                    )
                    entry["entry_comment"] = entry["comment"]
                    entry["recovery_focused"] = True

                    changes += 1

        return changes

    def _normalize_week_rows(
        self,
        rows: List[Dict[str, Any]],
        *,
        week_number: int,
    ) -> List[Dict[str, Any]]:
        return [{**row, "week_number": row.get("week_number", week_number)} for row in rows]

    def _assemble_payload(
        self,
        *,
        plan_id: int,
        week_number: int,
        rows: List[Dict[str, Any]],
        plan_start_date: date | None = None,
    ) -> Dict[str, Any]:
        return self._build_payload_from_rows(
            plan_id=plan_id,
            week_number=week_number,
            rows=rows,
            plan_start_date=plan_start_date,
        )

    def _annotate_and_enrich_payload(
        self,
        *,
        payload: Dict[str, Any],
        plan_id: int,
        week_number: int,
        rows: List[Dict[str, Any]],
        decision: ValidationDecision | None,
        daily_adjustment: DailyWgerAdjustment | None = None,
    ) -> int:
        is_test_week = any(bool(row.get("is_test")) for row in rows)
        self._annotate_week_payload(payload, week_number, is_test=is_test_week)
        if bool(getattr(settings, "WGER_EXPAND_STRETCH_ROUTINES", False)):
            self._expand_stretch_routines_for_export(payload)
        daily_changes = 0
        if daily_adjustment is None or daily_adjustment.adjust_runs:
            run_changes = self._apply_running_backoff_to_payload(
                payload,
                decision,
                only_day_of_week=daily_adjustment.day_of_week if daily_adjustment else None,
            )
            if daily_adjustment is not None:
                daily_changes += run_changes
        daily_changes += self._apply_daily_strength_adjustment_to_payload(
            payload,
            daily_adjustment,
        )
        self._annotate_adjustments_from_trace(payload=payload, plan_id=plan_id, week_number=week_number)
        return daily_changes

    def _apply_daily_strength_adjustment_to_payload(
        self,
        payload: Dict[str, Any],
        adjustment: DailyWgerAdjustment | None,
    ) -> int:
        """Apply today's readiness reduction to strength entries before wger export."""

        if adjustment is None or not adjustment.adjust_strength:
            return 0

        changes = 0

        for day in payload.get("days", []):
            try:
                day_of_week = int(day.get("day_of_week"))
            except (TypeError, ValueError):
                continue
            if day_of_week != adjustment.day_of_week:
                continue

            for entry in day.get("exercises", []):
                if self._is_non_strength_payload_entry(entry):
                    continue

                notes: list[str] = []
                target_weight = self._to_float(entry.get("target_weight_kg"))
                if target_weight is not None and adjustment.weight_multiplier < 0.999:
                    adjusted_weight = self._round_weight(target_weight * adjustment.weight_multiplier)
                    if abs(adjusted_weight - target_weight) >= 0.01:
                        entry["target_weight_kg"] = adjusted_weight
                        changes += 1
                        notes.append(
                            f"{self._format_weight(target_weight)} -> {self._format_weight(adjusted_weight)}"
                        )

                sets = self._to_int(entry.get("sets"))
                if sets is not None and adjustment.set_multiplier < 0.999:
                    adjusted_sets = max(1, int(round(sets * adjustment.set_multiplier)))
                    if adjusted_sets < sets:
                        entry["sets"] = adjusted_sets
                        changes += 1
                        notes.append(f"sets {sets} -> {adjusted_sets}")

                if adjustment.rir_increment:
                    current_rir = self._to_float(entry.get("rir"))
                    if current_rir is not None:
                        entry["rir"] = round(current_rir + adjustment.rir_increment, 1)
                        notes.append(f"RIR +{adjustment.rir_increment}")
                        changes += 1

                if not notes:
                    continue

                entry["recovery_focused"] = True
                note = f"Today readiness back-off: {', '.join(notes[:3])}"
                entry["comment"] = self._append_comment(entry.get("comment"), note)
                entry["entry_comment"] = entry["comment"]

        return changes

    @staticmethod
    def _is_non_strength_payload_entry(entry: Dict[str, Any]) -> bool:
        if bool(entry.get("is_cardio")):
            return True
        details = entry.get("details")
        details_map = details if isinstance(details, dict) else {}
        session_type = str(details_map.get("session_type") or "").strip().lower()
        return session_type in schedule_rules.RUN_SESSION_TYPES or session_type == schedule_rules.STRETCH_SESSION_TYPE

    @staticmethod
    def _append_comment(existing: Any, addition: str) -> str:
        base = str(existing or "").strip()
        if not base:
            return addition
        if addition in base:
            return base
        return f"{base} | {addition}"

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return None

    @staticmethod
    def _round_weight(weight_kg: float) -> float:
        return round(round(float(weight_kg) * 2) / 2, 2)

    @staticmethod
    def _format_weight(weight_kg: float) -> str:
        rounded = round(float(weight_kg), 2)
        if rounded.is_integer():
            return f"{int(rounded)}kg"
        return f"{rounded:.2f}".rstrip("0").rstrip(".") + "kg"

    def _annotate_adjustments_from_trace(self, *, payload: Dict[str, Any], plan_id: int, week_number: int) -> None:
        loader = getattr(self.dal, "get_plan_decision_trace", None)
        trace = loader(plan_id, week_number) if callable(loader) else []
        if not isinstance(trace, list):
            return
        notes: list[str] = []
        for item in trace:
            if not isinstance(item, dict):
                continue
            stage = str(item.get("stage") or "")
            detail = str(item.get("detail") or "").strip()
            if stage == "constraint_heavy_strength_run_quality":
                notes.append(f"Adjusted run quality: {detail}")
            elif stage in {"constraint_bilateral_recovery_backoff", "constraint_long_run_lower_strength"}:
                notes.append(f"Reduced accessory volume: {detail}")
        if notes:
            payload.setdefault("comments", [])
            payload["comments"].extend(notes)

    def _resolve_export_ids(self, payload: Dict[str, Any]) -> None:
        for day in payload.get("days", []):
            for exercise_payload in day.get("exercises", []):
                if exercise_payload.get("exercise") is None:
                    exercise_payload["exercise"] = self._resolve_export_exercise_id(exercise_payload)

    def _submit_payload_to_api(
        self,
        *,
        payload: Dict[str, Any],
        start_date: date,
        force_overwrite: bool,
    ) -> tuple[int, list[dict[str, Any]]]:
        routine_name = f"Pete-E Week {start_date.strftime('%Y-%m-%d')}"
        description = f"Automated plan for week starting {start_date.isoformat()}"
        if force_overwrite and self._supports_staged_routine_publish():
            existing = self.client.find_routine(routine_name, start_date)
            return self._publish_payload_staged(
                payload=payload,
                start_date=start_date,
                routine_name=routine_name,
                description=description,
                existing_routine=existing,
            )

        routine = self.client.find_or_create_routine(
            name=routine_name,
            description=description,
            start=start_date,
            end=start_date + timedelta(days=6),
        )
        routine_id = routine["id"]

        if force_overwrite:
            try:
                self.client.delete_all_days_in_routine(routine_id)
            except Exception as exc:
                fallback_name = self._fallback_routine_name(routine_name)
                log_utils.warn(
                    "Failed to clean existing wger routine "
                    f"{routine_id} for {start_date.isoformat()}: {exc}. "
                    f"Creating fallback routine {fallback_name!r}."
                )
                routine = self.client.find_or_create_routine(
                    name=fallback_name,
                    description=(
                        "Automated plan for week starting "
                        f"{start_date.isoformat()} after cleanup fallback"
                    ),
                    start=start_date,
                    end=start_date + timedelta(days=6),
                )
                routine_id = routine["id"]

        api_trace = self._write_payload_days(
            payload=payload,
            start_date=start_date,
            routine_id=routine_id,
        )
        return routine_id, api_trace

    def _replace_payload_in_api(
        self,
        *,
        payload: Dict[str, Any],
        start_date: date,
    ) -> tuple[int, list[dict[str, Any]], bool]:
        """Strictly replace the exact weekly routine, without fallback copies."""

        routine_name = f"Pete-E Week {start_date.strftime('%Y-%m-%d')}"
        finder = getattr(self.client, "find_routine", None)
        if not callable(finder):
            raise RuntimeError(
                "The configured wger client cannot safely find an exact routine for replacement."
            )

        routine = finder(routine_name, start_date)
        replaced_existing = routine is not None
        description = f"Automated plan for week starting {start_date.isoformat()}"
        if self._supports_staged_routine_publish():
            routine_id, api_trace = self._publish_payload_staged(
                payload=payload,
                start_date=start_date,
                routine_name=routine_name,
                description=description,
                existing_routine=routine,
            )
            return routine_id, api_trace, replaced_existing

        if routine is None:
            routine = self.client.find_or_create_routine(
                name=routine_name,
                description=description,
                start=start_date,
                end=start_date + timedelta(days=6),
            )

        routine_id = int(routine["id"])
        if replaced_existing:
            # Unlike the general force-overwrite path, repair must not create a
            # fallback copy when cleanup fails. A retry can safely finish
            # deleting any remaining days before the resend begins.
            self.client.delete_all_days_in_routine(routine_id)

        api_trace = self._write_payload_days(
            payload=payload,
            start_date=start_date,
            routine_id=routine_id,
        )
        return routine_id, api_trace, replaced_existing

    def _supports_staged_routine_publish(self) -> bool:
        return all(
            callable(getattr(self.client, method, None))
            for method in (
                "find_routine",
                "create_routine",
                "update_routine",
                "delete_routine",
            )
        )

    def _publish_payload_staged(
        self,
        *,
        payload: Dict[str, Any],
        start_date: date,
        routine_name: str,
        description: str,
        existing_routine: Dict[str, Any] | None,
    ) -> tuple[int, list[dict[str, Any]]]:
        """Write and verify a candidate routine before retiring the live one."""

        staging_name = self._staging_routine_name(routine_name)
        staging = self.client.create_routine(
            name=staging_name,
            description=f"{description} (staging)",
            start=start_date,
            end=start_date + timedelta(days=6),
        )
        staging_id = int(staging["id"])
        try:
            api_trace = self._write_payload_days(
                payload=payload,
                start_date=start_date,
                routine_id=staging_id,
            )
            self._verify_written_payload(payload=payload, api_trace=api_trace)
        except Exception:
            try:
                self.client.delete_routine(staging_id)
            except Exception as cleanup_exc:  # pragma: no cover - remote cleanup guard
                log_utils.warn(
                    f"Failed to remove incomplete Wger staging routine {staging_id}: {cleanup_exc}"
                )
            raise

        existing_id = None
        if existing_routine is not None:
            existing_id = int(existing_routine["id"])
            try:
                self.client.delete_routine(existing_id)
            except Exception:
                try:
                    self.client.delete_routine(staging_id)
                except Exception as cleanup_exc:  # pragma: no cover - remote cleanup guard
                    log_utils.warn(
                        f"Failed to remove Wger staging routine {staging_id}: {cleanup_exc}"
                    )
                raise

        try:
            self.client.update_routine(
                staging_id,
                name=routine_name,
                description=description,
                start=start_date,
                end=start_date + timedelta(days=6),
            )
        except Exception as exc:
            # The fully-written staging routine deliberately remains available.
            # If the old routine was already retired, deleting staging here would
            # recreate the original partial/empty-week failure mode.
            log_utils.error(
                "Wger staging routine was written but could not be promoted: "
                f"staging_id={staging_id}, replaced_routine_id={existing_id}, error={exc}",
                "ERROR",
            )
            raise RuntimeError(
                f"Wger routine promotion failed; complete staging routine {staging_id} was retained"
            ) from exc

        return staging_id, api_trace

    @staticmethod
    def _verify_written_payload(
        *,
        payload: Dict[str, Any],
        api_trace: list[dict[str, Any]],
    ) -> None:
        expected_days = payload.get("days", [])
        if len(api_trace) != len(expected_days):
            raise RuntimeError(
                f"Wger staging verification failed: expected {len(expected_days)} days, "
                f"wrote {len(api_trace)}"
            )
        for expected_day, written_day in zip(expected_days, api_trace):
            expected_exercises = expected_day.get("exercises", [])
            written_slots = written_day.get("slots", [])
            if len(written_slots) != len(expected_exercises):
                raise RuntimeError(
                    "Wger staging verification failed: "
                    f"day {expected_day.get('day_of_week')} expected "
                    f"{len(expected_exercises)} slots, wrote {len(written_slots)}"
                )
            for expected_entry, written_slot in zip(expected_exercises, written_slots):
                if expected_entry.get("exercise") and written_slot.get("entry_id") is None:
                    raise RuntimeError(
                        "Wger staging verification failed: slot entry missing for "
                        f"exercise {expected_entry.get('exercise')}"
                    )

    def _write_payload_days(
        self,
        *,
        payload: Dict[str, Any],
        start_date: date,
        routine_id: int,
    ) -> list[dict[str, Any]]:
        api_trace: list[dict[str, Any]] = []
        supports_full_export = all(
            hasattr(self.client, attr)
            for attr in ("create_day", "create_slot", "create_slot_entry", "set_config")
        )
        if not supports_full_export:
            log_utils.warn(
                "Wger client stub missing export endpoints; skipping API push but recording payload."
            )
            return api_trace

        for order, day_payload in enumerate(payload.get("days", []), start=1):
            day_number_raw = day_payload.get("day_of_week")
            day_of_week = int(day_number_raw) if day_number_raw is not None else order
            day_date = start_date + timedelta(days=(day_of_week - start_date.isoweekday()) % 7)
            day_name = day_date.strftime("%A %d %b")
            day_response = self.client.create_day(routine_id, order=order, name=day_name)

            slot_summaries: list[dict[str, Any]] = []
            for slot_order, exercise_payload in enumerate(day_payload.get("exercises", []), start=1):
                comment = exercise_payload.get("comment")
                slot_response = self.client.create_slot(day_response["id"], order=slot_order, comment=comment)

                exercise_id = exercise_payload.get("exercise")
                entry_response: Dict[str, Any] | None = None
                configs_sent: list[dict[str, Any]] = []
                if exercise_id:
                    entry_response = self.client.create_slot_entry(
                        slot_response["id"],
                        exercise_id=exercise_id,
                        order=1,
                        entry_type=exercise_payload.get("entry_type"),
                        comment=self._entry_comment_for_api(exercise_payload),
                    )
                    slot_entry_id = entry_response["id"]
                    configs_sent = self._apply_slot_entry_configs(
                        exercise_payload=exercise_payload,
                        exercise_id=exercise_id,
                        slot_entry_id=slot_entry_id,
                    )
                else:
                    details = exercise_payload.get("details")
                    session_type = details.get("session_type") if isinstance(details, dict) else None
                    log_utils.warn(
                        "Skipping slot entry creation due to missing exercise ID in payload. "
                        f"comment={comment!r}, session_type={session_type!r}"
                    )

                slot_summaries.append({
                    "slot_id": slot_response.get("id"),
                    "exercise_id": exercise_id,
                    "entry_id": None if entry_response is None else entry_response.get("id"),
                    "comment": comment,
                    "entry_comment": self._entry_comment_for_api(exercise_payload),
                    "entry_type": exercise_payload.get("entry_type"),
                    "configs": configs_sent,
                })

            api_trace.append({
                "day_id": day_response.get("id"),
                "day_of_week": day_of_week,
                "name": day_response.get("name"),
                "slots": slot_summaries,
            })

        return api_trace

    def _build_payload_from_rows(
        self,
        plan_id: int,
        week_number: int,
        rows: List[Dict[str, Any]],
        *,
        plan_start_date: date | None = None,
    ) -> Dict[str, Any]:
        """Transforms flat DB rows into the nested payload structure for export."""

        if not rows:
            plan = Plan(
                start_date=plan_start_date,
                weeks=[Week(week_number=week_number, workouts=[])],
            )
        else:
            plan = self.plan_mapper.from_rows({"start_date": plan_start_date}, rows)
        payload = self.payload_mapper.build_week_payload(
            plan,
            week_number,
            plan_id=plan_id,
        )
        if bool(getattr(settings, "WGER_EXPAND_STRETCH_ROUTINES", False)):
            self._expand_stretch_routines_for_export(payload)
        return payload

    def _annotate_week_payload(
        self,
        payload: Dict[str, Any],
        week_number: int,
        *,
        is_test: bool = False,
    ) -> None:
        """Enrich the payload with protocol notes and rest guidance."""

        for day in payload.get("days", []):
            main_set_index = 0
            exercises = day.get("exercises", [])
            for entry in exercises:
                exercise_id = entry.get("exercise")
                role = schedule_rules.classify_exercise(exercise_id)
                details = entry.get("details")
                if role == "cardio" or (
                    isinstance(details, dict)
                    and str(details.get("session_type") or "").strip().lower() == schedule_rules.STRETCH_SESSION_TYPE
                ):
                    entry["comment"] = schedule_rules.build_export_comment(
                        base_comment=entry.get("comment"),
                        details=details if isinstance(details, dict) else None,
                    )
                    entry["entry_comment"] = entry["comment"]
                    continue

                if role == "main":
                    main_set_index += 1
                    if not is_test and week_number != 4 and main_set_index <= 3:
                        entry["entry_type"] = "warmup"
                    if is_test:
                        percent = entry.get("percent_1rm")
                        if percent is None:
                            protocol = "AMRAP Test"
                        else:
                            protocol = f"AMRAP Test @ {float(percent):.1f}% TM"
                    else:
                        protocol = schedule_rules.describe_main_set(
                            week_number=week_number,
                            set_index=main_set_index,
                            percent=entry.get("percent_1rm"),
                            reps=entry.get("reps"),
                        )
                    weight_note = schedule_rules.format_weight_kg(entry.get("target_weight_kg"))
                elif role == "core":
                    protocol = schedule_rules.describe_core(entry.get("sets"), entry.get("reps"))
                    weight_note = None
                else:
                    protocol = schedule_rules.describe_assistance(entry.get("sets"), entry.get("reps"))
                    weight_note = None

                rest_seconds = schedule_rules.rest_seconds_for(
                    "main" if role == "main" else role,
                    week_number,
                )
                entry["rest_seconds"] = rest_seconds
                rest_note = schedule_rules.format_rest_seconds(rest_seconds)

                if protocol or rest_note:
                    comment_parts = [part for part in (protocol, weight_note, rest_note) if part]
                    if comment_parts and not entry.get("comment"):
                        entry["comment"] = " | ".join(comment_parts)

                entry["comment"] = schedule_rules.build_export_comment(
                    base_comment=entry.get("comment"),
                    details=entry.get("details"),
                )
                entry["entry_comment"] = entry["comment"]

    def _entry_comment_for_api(self, exercise_payload: Dict[str, Any]) -> str | None:
        raw_comment = exercise_payload.get("entry_comment") or exercise_payload.get("comment")
        if raw_comment is None:
            return None
        comment = str(raw_comment).strip()
        return comment[:100] or None
        """Perform entry comment for api."""

    def _apply_slot_entry_configs(
        self,
        *,
        exercise_payload: Dict[str, Any],
        exercise_id: int,
        slot_entry_id: int,
    ) -> list[dict[str, Any]]:
        configs_sent: list[dict[str, Any]] = []

        def send(config_type: str, value: Any) -> None:
            self.client.set_config(config_type, slot_entry_id, 1, value)
            configs_sent.append({"type": config_type, "iteration": 1, "value": value})
            """Perform send."""

        target_weight = exercise_payload.get("target_weight_kg")
        if target_weight is not None:
            send("weight", target_weight)
        elif schedule_rules.classify_exercise(exercise_id) == "main":
            log_utils.warn(
                "Skipping weight config for main lift due to missing target weight. "
                f"exercise_id={exercise_id}, comment={exercise_payload.get('comment')!r}"
            )

        details = exercise_payload.get("details")
        if (
            isinstance(details, dict)
            and str(details.get("session_type") or "").strip().lower()
            == schedule_rules.STRETCH_SESSION_TYPE
        ):
            return configs_sent

        for config_type, payload_key in (
            ("sets", "sets"),
            ("reps", "reps"),
            ("rir", "rir"),
            ("rest", "rest_seconds"),
        ):
            value = exercise_payload.get(payload_key)
            if value is not None:
                send(config_type, value)

        return configs_sent
        """Perform apply slot entry configs."""

    def _expand_stretch_routines_for_export(self, payload: Dict[str, Any]) -> None:
        for day in payload.get("days", []):
            expanded: list[dict[str, Any]] = []
            for entry in day.get("exercises", []):
                expanded.extend(self._expand_stretch_entry(entry))
            day["exercises"] = expanded
        """Perform expand stretch routines for export."""

    def _expand_stretch_entry(self, entry: Dict[str, Any]) -> list[dict[str, Any]]:
        details = entry.get("details")
        if not isinstance(details, dict):
            return [entry]
        session_type = str(details.get("session_type") or "").strip().lower()
        if session_type != schedule_rules.STRETCH_SESSION_TYPE:
            return [entry]

        steps = details.get("steps")
        if not isinstance(steps, list) or not steps:
            return [entry]

        parent_name = str(
            details.get("display_name")
            or entry.get("exercise_name")
            or entry.get("comment")
            or "Stretch routine"
        ).strip()
        valid_steps = [step for step in steps if isinstance(step, dict) and step.get("name")]
        total_steps = len(valid_steps)
        if not valid_steps:
            return [entry]

        expanded: list[dict[str, Any]] = []
        for index, step in enumerate(valid_steps, start=1):
            step_name = str(step["name"]).strip()
            prescription = str(step.get("prescription") or "").strip()
            slot_comment = f"{parent_name} {index}/{total_steps}: {step_name}"
            if prescription:
                slot_comment = f"{slot_comment} - {prescription}"

            step_payload = dict(entry)
            step_payload.update(
                {
                    "exercise": None,
                    "exercise_name": step_name,
                    "sets": 1,
                    "reps": None,
                    "rir": None,
                    "target_weight_kg": None,
                    "percent_1rm": None,
                    "comment": slot_comment,
                    "entry_comment": prescription or slot_comment,
                    "details": {
                        "session_type": schedule_rules.STRETCH_SESSION_TYPE,
                        "routine_key": details.get("routine_key"),
                        "parent_routine": parent_name,
                        "source": details.get("source"),
                        "display_name": step_name,
                        "step_index": index,
                        "step_count": total_steps,
                        "step": dict(step),
                    },
                }
            )
            step_payload.pop("rest_seconds", None)
            step_payload.pop("entry_type", None)
            expanded.append(step_payload)

        return expanded
        """Perform expand stretch entry."""

    def _resolve_export_exercise_id(self, exercise_payload: Dict[str, Any]) -> int | None:
        details = exercise_payload.get("details")
        if not isinstance(details, dict):
            return None

        session_type = str(details.get("session_type") or "").strip().lower()
        if session_type != schedule_rules.STRETCH_SESSION_TYPE:
            return None

        display_name = (
            str(exercise_payload.get("exercise_name") or "").strip()
            or str(details.get("display_name") or "").strip()
            or str(exercise_payload.get("comment") or "").strip()
        )
        if not display_name:
            return None

        description = self._stretch_export_description(details)
        return self.client.ensure_custom_exercise(
            name=display_name,
            description=description,
        )
        """Perform resolve export exercise id."""

    def _stretch_export_description(self, details: Dict[str, Any]) -> str:
        step = details.get("step")
        if isinstance(step, dict):
            name = str(details.get("display_name") or step.get("name") or "Stretch exercise").strip()
            parent = str(details.get("parent_routine") or "").strip()
            source = str(details.get("source") or "").strip()
            prescription = str(step.get("prescription") or "").strip()
            movement_type = str(step.get("movement_type") or "").strip()

            lines = [name]
            if parent:
                lines.append(f"Part of: {parent}")
            if source:
                lines.append(f"Source: {source}")
            if prescription:
                lines.append(f"Prescription: {prescription}")
            if movement_type:
                lines.append(f"Type: {movement_type}")
            if step.get("is_isometric"):
                lines.append("Includes isometric hold.")
            if step.get("includes_isometric_hold"):
                hold_seconds = step.get("hold_seconds")
                if hold_seconds:
                    lines.append(f"Includes dynamic movement plus {hold_seconds}s hold.")
                else:
                    lines.append("Includes dynamic movement plus hold.")
            return "\n".join(lines).strip()

        return schedule_rules.stretch_routine_description(details)
        """Perform stretch export description."""
