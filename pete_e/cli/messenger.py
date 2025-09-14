"""
Command-line interface for generating and sending reports via Telegram.

This script is the primary entry point for the pete_reports.yml workflow.
It uses the Orchestrator to generate different types of reports (daily,
weekly, cycle) and sends them to the configured Telegram chat.

Refactored to:
- Use the modern DAL for all data access.
- Delegate complex logic to the Orchestrator service.
- Read all credentials and settings from the central config.
"""
import argparse
from datetime import date

from pete_e.config import settings
from pete_e.core.orchestrator import Orchestrator
from pete_e.data_access.postgres_dal import PostgresDal
from pete_e.infra.telegram_sender import send_telegram_message
from pete_e.infra import log_utils

def main():
    """Parses CLI arguments and triggers the appropriate report generation."""
    parser = argparse.ArgumentParser(description="Generate and send Pete-E reports.")
    parser.add_argument(
        "--type",
        choices=["daily", "weekly", "cycle"],
        required=True,
        help="The type of report to generate.",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Optional start date for cycle report (YYYY-MM-DD)."
    )
    args = parser.parse_args()

    log_utils.log_message(f"Messenger CLI invoked for '{args.type}' report.", "INFO")

    # 1. Initialize dependencies
    if not settings.DATABASE_URL:
        raise RuntimeError("DATABASE_URL not configured for PostgresDal")
    try:
        dal = PostgresDal()
    except Exception as e:  # pragma: no cover - misconfiguration path
        raise RuntimeError(f"Postgres DAL init failed: {e}") from e
    orchestrator = Orchestrator(dal)

    # 2. Generate the report content using the orchestrator
    message = ""
    if args.type == "daily":
        message = orchestrator.generate_daily_report(date.today())
    elif args.type == "weekly":
        message = orchestrator.generate_weekly_report(date.today())
    elif args.type == "cycle":
        start_date = date.fromisoformat(args.start_date) if args.start_date else None
        message = orchestrator.generate_cycle_report(start_date)

    # 3. Send the message via Telegram
    if message:
        send_telegram_message(
            token=settings.TELEGRAM_TOKEN,
            chat_id=settings.TELEGRAM_CHAT_ID,
            message=message
        )
        log_utils.log_message("Report successfully sent to Telegram.", "INFO")
    else:
        log_utils.log_message("No message generated, nothing sent.", "WARN")


if __name__ == "__main__":
    main()
