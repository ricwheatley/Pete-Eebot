#!/usr/bin/env python3
# scripts/generate_plan.py
"""
Creates a new 4-week training block and exports the first week to wger
using the refactored application services.
"""
import argparse
import datetime as dt

from pete_e.application.services import PlanService, WgerExportService
from pete_e.infrastructure.postgres_dal import PostgresDal
from pete_e.infrastructure.wger_client import WgerClient
from pete_e.infrastructure import log_utils

def main() -> None:
    parser = argparse.ArgumentParser(description="Create a 4-week plan and export week 1 to wger")
    parser.add_argument("--start-date", required=True, help="Monday date for the plan start, e.g. 2025-10-27")
    parser.add_argument("--dry-run", action="store_true", help="Prepare export but do not send to wger")
    args = parser.parse_args()

    start_date = dt.date.fromisoformat(args.start_date)
    
    # 1. Initialize our clean, consolidated modules
    dal = PostgresDal()
    wger_client = WgerClient()
    plan_service = PlanService(dal)
    export_service = WgerExportService(dal, wger_client)

    try:
        # 2. Use the service to create and persist the plan
        plan_id = plan_service.create_and_persist_531_block(start_date)
        log_utils.info(f"Successfully created plan_id: {plan_id}")

        # 3. Use the service to export the first week
        export_result = export_service.export_plan_week(
            plan_id=plan_id,
            week_number=1,
            start_date=start_date,
            force_overwrite=True,
            dry_run=args.dry_run
        )
        log_utils.info(f"Export result: {export_result}")

    except Exception as e:
        log_utils.error(f"Script failed: {e}", exc_info=True)
        raise
    finally:
        dal.close()

if __name__ == "__main__":
    main()