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

        # Future enhancements may branch between strength-test weeks and 5/3/1 blocks
        # based on macrocycle state. For now we always generate the next full block.
        log_utils.info(
            "Creating next macrocycle block via PlanService.create_next_plan_for_cycle..."
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
                        if sets is not None:
                            self.client.set_config("sets", slot_entry_id, 1, sets)
                        if reps is not None:
                            self.client.set_config("reps", slot_entry_id, 1, reps)
                        if rir is not None:
                            self.client.set_config("rir", slot_entry_id, 1, rir)
                    else:
                        log_utils.warn(
                            "Skipping slot entry creation due to missing exercise ID in payload."
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

        # 5. Log the export result
        self.dal.record_wger_export(
            plan_id,
            week_number,
            payload,
            response={"routine_id": routine_id, "days": api_trace},
            routine_id=routine_id,
        )
        log_utils.info(f"Successfully exported plan {plan_id}, week {week_number} to wger routine {routine_id}.")
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
        self._annotate_week_payload(payload, week_number)
        return payload

    def _annotate_week_payload(self, payload: Dict[str, Any], week_number: int) -> None:
        """Enrich the payload with protocol notes and rest guidance."""

        for day in payload.get("days", []):
            main_set_index = 0
            exercises = day.get("exercises", [])
            for entry in exercises:
                exercise_id = entry.get("exercise")
                role = schedule_rules.classify_exercise(exercise_id)
                if role == "cardio":
                    continue

                if role == "main":
                    main_set_index += 1
                    protocol = schedule_rules.describe_main_set(
                        week_number=week_number,
                        set_index=main_set_index,
                        percent=entry.get("percent_1rm"),
                        reps=entry.get("reps"),
                    )
                elif role == "core":
                    protocol = schedule_rules.describe_core(entry.get("sets"), entry.get("reps"))
                else:
                    protocol = schedule_rules.describe_assistance(entry.get("sets"), entry.get("reps"))

                rest_seconds = schedule_rules.rest_seconds_for(
                    "main" if role == "main" else role,
                    week_number,
                )
                rest_note = schedule_rules.format_rest_seconds(rest_seconds)

                if protocol or rest_note:
                    comment_parts = [part for part in (protocol, rest_note) if part]
                    if comment_parts and not entry.get("comment"):
                        entry["comment"] = " | ".join(comment_parts)
