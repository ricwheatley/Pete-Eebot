# (Functional) **Command-line interface** (Typer app) exposing main features.

"""
Main Command-Line Interface for the Pete-Eebot application.

This script provides a single entry point for all major operations,
including running the daily data sync, ingesting new data, and sending
notifications.
"""
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from typing_extensions import Annotated

import typer

from pete_e.application.apple_dropbox_ingest import run_apple_health_ingest
from pete_e.application.sync import run_sync_with_retries, run_withings_only_with_retries
from pete_e.domain import body_age
from pete_e.cli.status import DEFAULT_TIMEOUT_SECONDS, render_results, run_status_checks
from pete_e.infrastructure import log_utils
from pete_e.infrastructure import withings_oauth_helper
from pete_e.infrastructure.withings_client import WithingsClient
from pete_e.cli.telegram import telegram as telegram_command

if TYPE_CHECKING:  # pragma: no cover - import for type checking only
    from pete_e.application.orchestrator import Orchestrator as OrchestratorType
else:  # pragma: no cover - runtime fallback
    OrchestratorType = object


def _build_orchestrator() -> "OrchestratorType":
    """Lazy import helper to avoid CLI/orchestrator circular dependencies."""
    from pete_e.application.orchestrator import Orchestrator as _Orchestrator

    return _Orchestrator()


def _format_body_age_line(trend) -> str | None:
    if trend is None:
        return None
    value = getattr(trend, "value", None)
    delta = getattr(trend, "delta", None)
    if value is None:
        return "Body Age: n/a"
    line = f"Body Age: {value:.1f}y"
    if delta is None:
        return f"{line} (7d delta n/a)"
    return f"{line} (7d delta {delta:+.1f}y)"


def _append_line(base: str | None, addition: str) -> str:
    base_text = "" if base is None else str(base)
    if not addition:
        return base_text
    if not base_text:
        return addition
    if not base_text.endswith("\n"):
        base_text = f"{base_text}\n"
    return f"{base_text}{addition}"




def build_daily_summary(
    *,
    orchestrator: "OrchestratorType | None" = None,
    target_date: date | None = None,
) -> str:
    """Generate the daily summary narrative for the requested date."""
    orch = orchestrator or _build_orchestrator()
    summary_value = orch.get_daily_summary(target_date=target_date)
    summary_text = "" if summary_value is None else str(summary_value)

    target = target_date or (date.today() - timedelta(days=1))
    trend = body_age.get_body_age_trend(getattr(orch, "dal", None), target_date=target)
    body_age_line = _format_body_age_line(trend)
    if body_age_line:
        summary_text = _append_line(summary_text, body_age_line)

    return summary_text


def send_daily_summary(
    *,
    orchestrator: "OrchestratorType | None" = None,
    target_date: date | None = None,
    summary_text: str | None = None,
) -> str:
    """Send the daily summary via Telegram and return the content that was sent."""
    orch = orchestrator or _build_orchestrator()
    if summary_text is None:
        summary_value = build_daily_summary(orchestrator=orch, target_date=target_date)
    else:
        summary_value = summary_text
    summary_str = "" if summary_value is None else str(summary_value)

    if not summary_str.strip():
        return summary_str

    sent = orch.send_telegram_message(summary_str)
    if not sent:
        raise RuntimeError("Telegram send for daily summary failed.")

    return summary_str


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
    result = run_sync_with_retries(days=days, retries=retries)
    if result.success:
        typer.echo("Manual sync completed. Summary written to logs/pete_history.log.")
        raise typer.Exit(code=0)
    typer.echo("Manual sync finished with errors. Check logs/pete_history.log for details.")
    raise typer.Exit(code=1)


@app.command(name="withings-sync")
def withings_sync(
    days: Annotated[int, typer.Option(help="Number of past days to backfill.")] = 7,
    retries: Annotated[int, typer.Option(help="Number of retries on failure.")] = 3,
) -> None:
    """Run only the Withings portion of the sync pipeline."""
    log_utils.log_message(f"Starting Withings-only sync for the last {days} days.", "INFO")
    result = run_withings_only_with_retries(days=days, retries=retries)
    if result.success:
        typer.echo("Withings-only sync completed. Summary written to logs/pete_history.log.")
        raise typer.Exit(code=0)
    typer.echo("Withings-only sync finished with errors. Check logs/pete_history.log for details.")
    raise typer.Exit(code=1)


@app.command()
def status(
    timeout: Annotated[float, typer.Option('--timeout', help='Override per-dependency timeout in seconds.')] = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Quick health check for database, Dropbox, and Withings integrations."""
    results = run_status_checks(timeout=timeout)
    typer.echo(render_results(results))
    exit_code = 0 if all(result.ok for result in results) else 1
    raise typer.Exit(code=exit_code)


@app.command(name="ingest-apple")
def ingest_apple() -> None:
    """
    Ingest Apple Health data delivered via Dropbox.

    Downloads new HealthAutoExport files from Dropbox, parses them, and
    persists the resulting metrics to the database.
    """
    try:
        report = run_apple_health_ingest()
    except Exception as exc:  # pragma: no cover - defensive guardrail
        log_utils.log_message(f"Apple Health Dropbox ingestion failed: {exc}", "ERROR")
        raise typer.Exit(code=1)

    processed_files = len(report.sources)
    log_utils.log_message(
        (
            "Apple Health Dropbox ingestion finished. "
            f"Processed {processed_files} file(s), "
            f"{report.workouts} workouts, and {report.daily_points} metric points."
        ),
        "INFO",
    )


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
        today = date.today()
        start_date = today + timedelta(days=-today.weekday(), weeks=1)

    log_utils.log_message("Invoking plan generator...", "INFO")
    orchestrator = _build_orchestrator()
    plan_id = orchestrator.generate_and_deploy_next_plan(start_date=start_date, weeks=weeks)

    if plan_id > 0:
        log_utils.log_message(f"New plan (ID: {plan_id}) deployed successfully!", "INFO")
        raise typer.Exit(code=0)
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

    orchestrator = _build_orchestrator()

    if summary:
        log_utils.log_message("Generating daily summary...", "INFO")
        daily_summary = build_daily_summary(orchestrator=orchestrator)
        print("--- Daily Summary ---")
        print(daily_summary)
        if send:
            try:
                send_daily_summary(orchestrator=orchestrator, summary_text=daily_summary)
            except Exception as exc:  # pragma: no cover - defensive guardrail
                log_utils.log_message(f"Failed to send daily summary via Telegram: {exc}", "ERROR")
                raise typer.Exit(code=1)

    if plan:
        log_utils.log_message("Generating weekly plan...", "INFO")
        weekly_plan = orchestrator.get_week_plan_summary()
        print("--- Weekly Plan ---")
        print(weekly_plan)
        if send:
            if not orchestrator.send_telegram_message(weekly_plan):
                log_utils.log_message("Failed to send weekly plan via Telegram.", "ERROR")
                raise typer.Exit(code=1)


@app.command("refresh-withings")
def refresh_withings_tokens() -> None:
    """
    Force a Withings token refresh and save the new tokens to disk.
    """
    try:
        client = WithingsClient()
        tokens = client._refresh_access_token()  # returns body from API
        typer.echo("[OK] Withings tokens refreshed.")
        typer.echo(f"Access token:  {tokens['access_token'][:12]}... (truncated)")
        typer.echo(f"Refresh token: {tokens['refresh_token'][:12]}... (truncated)")
    except Exception as e:
        log_utils.log_message(f"Failed to refresh Withings tokens: {e}", "ERROR")
        raise typer.Exit(code=1)


@app.command("withings-auth-url")
def withings_auth_url() -> None:
    """
    Print the Withings authorization URL for first-time setup.
    Open it in your browser, log in, and approve Pete-Eebot.
    """
    url = withings_oauth_helper.build_authorize_url()
    typer.echo("-> Visit this URL to authorize Pete-Eebot with Withings:")
    typer.echo(url)


@app.command("withings-exchange-code")
def withings_exchange_code(code: str) -> None:
    """
    Exchange an authorization code (from Withings redirect) for tokens.
    Saves tokens to .withings_tokens.json for future use.
    """
    try:
        tokens = withings_oauth_helper.exchange_code_for_tokens(code)
        client = WithingsClient()
        client._save_tokens(tokens)

        typer.echo("[OK] Successfully exchanged code for tokens.")
        typer.echo(f"Access token:  {tokens['access_token'][:12]}... (truncated)")
        typer.echo(f"Refresh token: {tokens['refresh_token'][:12]}... (truncated)")
        typer.echo("\nTokens have been saved to .withings_tokens.json")
    except Exception as e:
        log_utils.log_message(f"Failed to exchange code: {e}", "ERROR")
        raise typer.Exit(code=1)


app.command()(telegram_command)

if __name__ == "__main__":
    app()



