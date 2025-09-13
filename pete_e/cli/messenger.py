import argparse
import sys
from datetime import date

# Import config to check for database URL
from pete_e.config import settings

# Import both DAL implementations
from pete_e.data_access.json_dal import JsonDal
from pete_e.data_access.postgres_dal import PostgresDal

# Import core application components
from pete_e.core.orchestrator import PeteE
from pete_e.core import sync
from pete_e.infra import log_utils


def main() -> None:
    """
    Main entrypoint for the Pete-E command-line interface.
    Initializes the appropriate Data Access Layer (DAL) and runs the requested
    orchestrator command.
    """
    parser = argparse.ArgumentParser(description="Pete-E orchestrator CLI")
    parser.add_argument(
        "--type",
        choices=["daily", "weekly", "cycle", "random"],
        required=True,
        help="Type of run to execute",
    )
    parser.add_argument("--start-date", type=str, help="Start date for cycle runs (YYYY-MM-DD)")
    args = parser.parse_args()

    # --- DAL Selection Logic ---
    # This is the "switch" that determines whether to use the database or JSON files.
    if settings.DATABASE_URL:
        log_utils.log_message("DATABASE_URL found, attempting to use PostgresDal.", "INFO")
        try:
            dal = PostgresDal()
            # The pool in PostgresDal connects on initialization, so if this passes,
            # the database connection is likely working.
        except Exception as e:
            log_utils.log_message(f"CRITICAL: Failed to initialize PostgresDal. Is the database running and DATABASE_URL correct? Error: {e}", "CRITICAL")
            sys.exit(1) # Exit with an error code if we can't connect to the DB.
    else:
        log_utils.log_message("DATABASE_URL not set, falling back to JsonDal.", "WARN")
        dal = JsonDal()

    # Instantiate the orchestrator and inject the chosen DAL
    pete = PeteE(dal=dal)

    log_utils.log_message(f"Executing run type: {args.type}")

    # The rest of the application logic is the same, but now it uses the DAL
    if args.type == "daily":
        if sync.run_sync_with_retries(dal=dal):
            pete.send_daily_feedback()
        else:
            log_utils.log_message("Sync failed after multiple retries - aborting daily feedback.", "ERROR")
    
    elif args.type == "weekly":
        if sync.run_sync_with_retries(dal=dal):
            pete.send_weekly_feedback()
        else:
            log_utils.log_message("Sync failed after multiple retries - aborting weekly feedback.", "ERROR")

    elif args.type == "cycle":
        start_date_obj = date.fromisoformat(args.start_date) if args.start_date else None
        if sync.run_sync_with_retries(dal=dal):
            pete.run_cycle(start_date=start_date_obj)
        else:
            log_utils.log_message("Sync failed after multiple retries - aborting cycle.", "ERROR")

    elif args.type == "random":
        pete.send_random_message()


if __name__ == "__main__":
    main()
