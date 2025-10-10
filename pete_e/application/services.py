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

        # ... logic to loop through payload, create days, slots, entries, configs ...
        # This will be a more detailed implementation based on wger_exporter logic.
        
        # 5. Log the export result
        self.dal.record_wger_export(plan_id, week_number, payload, response={"routine_id": routine_id}, routine_id=routine_id)
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
        return self.payload_mapper.build_week_payload(
            plan,
            week_number,
            plan_id=plan_id,
        )
