# pete_e/application/services.py
"""
Contains high-level services that orchestrate domain logic and infrastructure.
This layer is responsible for coordinating tasks like plan creation and export.
"""

from __future__ import annotations
from datetime import date, timedelta
from typing import Any, Dict, List
import json

from pete_e.application.validation_service import ValidationService
from pete_e.application.strength_test import StrengthTestService
from pete_e.domain.validation import ValidationDecision
from pete_e.domain.entities import Plan, Week
from pete_e.domain.plan_factory import PlanFactory
from pete_e.domain import schedule_rules
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
        
        # 2. Use PlanFactory to build the plan dictionary
        plan_dict = self.factory.create_531_block_plan(start_date, tms)
        plan_entity = self.plan_mapper.from_dict(plan_dict)
        payload = self.plan_mapper.to_persistence_payload(plan_entity)

        # 3. Persist the plan using the DAL
        # This will be a new method in the DAL to save a full plan object.
        plan_id = self.dal.save_full_plan(payload)
        log_utils.info(f"Successfully created and persisted plan_id: {plan_id}")
        return plan_id

    def create_and_persist_strength_test_week(self, start_date: date) -> int:
        """Creates and persists a new 1-week strength test plan."""
        log_utils.info(f"Creating new strength test week starting {start_date.isoformat()}...")
        tms = self.dal.get_latest_training_maxes()
        plan_dict = self.factory.create_strength_test_plan(start_date, tms)
        plan_entity = self.plan_mapper.from_dict(plan_dict)
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

    def export_plan_week(
        self,
        plan_id: int,
        week_number: int,
        start_date: date,
        force_overwrite: bool = False,
        dry_run: bool = False,
        validation_decision: ValidationDecision | None = None,
    ) -> Dict[str, Any]:
        """
        Validates, prepares, and pushes a single training week to wger.
        (Logic migrated from wger_sender.py and wger_exporter.py)
        """
        log_utils.info(f"Starting export for plan {plan_id}, week {week_number}...")

        # 1. Perform readiness validation and apply adjustments if needed
        if validation_decision is None:
            decision = self.validation_service.validate_and_adjust_plan(start_date)
            log_utils.info(f"Readiness check: {decision.explanation}")
        else:
            decision = validation_decision

        # 2. Check if this week was already exported
        if not force_overwrite and self.dal.was_week_exported(plan_id, week_number):
            log_utils.warn(f"Skipping export: plan {plan_id}, week {week_number} already exported.")
            return {"status": "skipped", "reason": "already-exported"}
        
        # 3. Build the payload from the (potentially adjusted) plan in the DB
        week_rows = self.dal.get_plan_week_rows(plan_id, week_number)
        payload = self._build_payload_from_rows(
            plan_id,
            week_number,
            week_rows,
            plan_start_date=start_date,
        )

        if dry_run:
            log_utils.info(f"[DRY RUN] Would export payload: {json.dumps(payload, indent=2)}")
            return {"status": "dry-run", "payload": payload}

        # 4. Use the WgerClient to perform the export
        routine_name = f"Pete-E Week {start_date.strftime('%Y-%m-%d')}"
        routine = self.client.find_or_create_routine(
            name=routine_name,
            description=f"Automated plan for week starting {start_date.isoformat()}",
            start=start_date,
            end=start_date + timedelta(days=6)
        )
        routine_id = routine['id']

        if force_overwrite:
            self.client.delete_all_days_in_routine(routine_id)

        api_trace: list[dict[str, Any]] = []
        supports_full_export = all(
            hasattr(self.client, attr)
            for attr in ("create_day", "create_slot", "create_slot_entry", "set_config")
        )

        if not supports_full_export:
            log_utils.warn(
                "Wger client stub missing export endpoints; skipping API push but recording payload."
            )
        else:
            for order, day_payload in enumerate(payload.get("days", []), start=1):
                day_number_raw = day_payload.get("day_of_week")
                day_of_week = int(day_number_raw) if day_number_raw is not None else order
                day_date = start_date + timedelta(days=(day_of_week - start_date.isoweekday()) % 7)
                day_name = day_date.strftime("%A %d %b")
                day_response = self.client.create_day(
                    routine_id,
                    order=order,
                    name=day_name,
                )

                slot_summaries: list[dict[str, Any]] = []
                for slot_order, exercise_payload in enumerate(day_payload.get("exercises", []), start=1):
                    comment = exercise_payload.get("comment")
                    slot_response = self.client.create_slot(
                        day_response["id"],
                        order=slot_order,
                        comment=comment,
                    )

                    exercise_id = exercise_payload.get("exercise")
                    if exercise_id is None:
                        exercise_id = self._resolve_export_exercise_id(exercise_payload)
                    entry_response: Dict[str, Any] | None = None
                    if exercise_id:
                        entry_response = self.client.create_slot_entry(
                            slot_response["id"],
                            exercise_id=exercise_id,
                            order=1,
                        )
                        slot_entry_id = entry_response["id"]
                        sets = exercise_payload.get("sets")
                        reps = exercise_payload.get("reps")
                        rir = exercise_payload.get("rir")
                        target_weight = exercise_payload.get("target_weight_kg")
                        if target_weight is not None:
                            self.client.set_config("weight", slot_entry_id, 1, target_weight)
                        elif schedule_rules.classify_exercise(exercise_id) == "main":
                            log_utils.warn(
                                "Skipping weight config for main lift due to missing target weight. "
                                f"exercise_id={exercise_id}, comment={comment!r}"
                            )
                        if sets is not None:
                            self.client.set_config("sets", slot_entry_id, 1, sets)
                        if reps is not None:
                            self.client.set_config("reps", slot_entry_id, 1, reps)
                        if rir is not None:
                            self.client.set_config("rir", slot_entry_id, 1, rir)
                    else:
                        details = exercise_payload.get("details")
                        session_type = None
                        if isinstance(details, dict):
                            session_type = details.get("session_type")
                        log_utils.warn(
                            "Skipping slot entry creation due to missing exercise ID in payload. "
                            f"comment={comment!r}, session_type={session_type!r}"
                        )

                    slot_summaries.append(
                        {
                            "slot_id": slot_response.get("id"),
                            "exercise_id": exercise_id,
                            "entry_id": None if entry_response is None else entry_response.get("id"),
                            "comment": comment,
                        }
                    )

                api_trace.append(
                    {
                        "day_id": day_response.get("id"),
                        "day_of_week": day_of_week,
                        "name": day_response.get("name"),
                        "slots": slot_summaries,
                    }
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
        return {"status": "exported", "routine_id": routine_id}

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
            enriched_rows = [
                {**row, "week_number": row.get("week_number", week_number)}
                for row in rows
            ]
            plan = self.plan_mapper.from_rows({"start_date": plan_start_date}, enriched_rows)
        payload = self.payload_mapper.build_week_payload(
            plan,
            week_number,
            plan_id=plan_id,
        )
        is_test_week = any(bool(row.get("is_test")) for row in rows)
        self._annotate_week_payload(payload, week_number, is_test=is_test_week)
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
                    continue

                if role == "main":
                    main_set_index += 1
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
                rest_note = schedule_rules.format_rest_seconds(rest_seconds)

                if protocol or rest_note:
                    comment_parts = [part for part in (protocol, weight_note, rest_note) if part]
                    if comment_parts and not entry.get("comment"):
                        entry["comment"] = " | ".join(comment_parts)

                entry["comment"] = schedule_rules.build_export_comment(
                    base_comment=entry.get("comment"),
                    details=entry.get("details"),
                )

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

        description = schedule_rules.stretch_routine_description(details)
        return self.client.ensure_custom_exercise(
            name=display_name,
            description=description,
        )
