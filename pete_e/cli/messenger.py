"""
Main Command-Line Interface for the Pete-Eebot application.

This script provides a single entry point for all major operations,
including running the daily data sync, ingesting new data, and sending
notifications.
"""
import sys
from typing_extensions import Annotated

import typer

# Import the core logic functions we want to expose as commands
from pete_e.core.apple_ingest import ingest_and_process_apple_data
from pete_e.core.sync import run_sync_with_retries
from pete_e.core.orchestrator import Orchestrator
from pete_e.infra import log_utils
from datetime import datetime, date, timedelta

# Create the Typer application object
app = typer.Typer(
    name="pete-e",
    help="CLI for Pete-Eebot, your personal health and fitness orchestrator.",
    add_completion=False,
)

@app.command()
def sync(
    days: Annotated[int, typer.Option(help="Number of past days to backfill.")] = 7,
    retries: Annotated[int, typer.Option(help="Number of retries on failure.")] = 3,
) -> None:
    """
    Run the daily data synchronization.

    Fetches the latest data from all sources (Withings, Apple, Wger),
    updates the database, and recalculates body age.
    """
    log_utils.log_message(f"Starting manual sync for the last {days} days.", "INFO")
    success = run_sync_with_retries(days=days, retries=retries)
    if success:
        log_utils.log_message("Manual sync completed successfully.", "INFO")
        raise typer.Exit(code=0)
    else:
        log_utils.log_message("Manual sync finished with errors.", "ERROR")
        raise typer.Exit(code=1)


@app.command(name="ingest-apple")
def ingest_apple() -> None:
    """
    Ingest and process Apple Health data from Tailscale.

    Checks the Tailscale inbox for new .zip files, processes them,
    and archives them.
    """
    success = ingest_and_process_apple_data()
    if not success:
        log_utils.log_message("Apple Health ingestion failed.", "ERROR")
        raise typer.Exit(code=1)
    log_utils.log_message("Apple Health ingestion process finished.", "INFO")

@app.command()
def plan(
    weeks: Annotated[int, typer.Option(help="The duration of the new plan in weeks.")] = 4,
    start_date_str: Annotated[str, typer.Option("--start-date", help="Start date in YYYY-MM-DD format. Defaults to next Monday.")] = None,
) -> None:
    """
    Generate and deploy a new training plan for the next block.
    """
    if start_date_str:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    else:
        # Default to the next upcoming Monday
        today = date.today()
        start_date = today + timedelta(days=-today.weekday(), weeks=1)

    log_utils.log_message("Invoking plan generator...", "INFO")
    orchestrator = Orchestrator()
    plan_id = orchestrator.generate_and_deploy_next_plan(start_date=start_date, weeks=weeks)

    if plan_id > 0:
        log_utils.log_message(f"New plan (ID: {plan_id}) deployed successfully!", "INFO")
        raise typer.Exit(code=0)
    else:
        log_utils.log_message("Failed to deploy new plan.", "ERROR")
        raise typer.Exit(code=1)
    

@app.command()
def message(
    send: Annotated[bool, typer.Option("--send", help="Send the generated message via Telegram.")] = False,
    summary: Annotated[bool, typer.Option("--summary", help="Generate and send the daily summary.")] = False,
    plan: Annotated[bool, typer.Option("--plan", help="Generate and send the weekly training plan.")] = False,
) -> None:
    """
    Generate and optionally send messages (daily summary or weekly plan).
    """
    if not summary and not plan:
        log_utils.log_message("Please specify a message type to generate: --summary or --plan", "WARN")
        raise typer.Exit(code=1)

    orchestrator = Orchestrator()
    if summary:
        log_utils.log_message("Generating daily summary...", "INFO")
        daily_summary = orchestrator.get_daily_summary()
        print("--- Daily Summary ---")
        print(daily_summary)
        if send:
            orchestrator.send_telegram_message(daily_summary)

    if plan:
        log_utils.log_message("Generating weekly plan...", "INFO")
        weekly_plan = orchestrator.get_week_plan_summary()
        print("--- Weekly Plan ---")
        print(weekly_plan)
        if send:
            orchestrator.send_telegram_message(weekly_plan)


if __name__ == "__main__":
    app()