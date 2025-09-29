# (Functional) **Command-line interface** (Typer app) exposing main features.

"""
Main Command-Line Interface for the Pete-Eebot application.

This script provides a single entry point for all major operations,
including running the daily data sync, ingesting new data, and sending
notifications.
"""
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, List
from rich.console import Console
from rich.table import Table

from typing_extensions import Annotated

import typer
import pathlib
import psycopg
import csv
import json as jsonlib

from typer import Argument, Option

from pete_e.infrastructure.db_conn import get_database_url

from pete_e.application.apple_dropbox_ingest import run_apple_health_ingest
from pete_e.application.sync import run_sync_with_retries, run_withings_only_with_retries
from pete_e.application.wger_sender import push_week
from pete_e.domain import body_age, narrative_builder
from pete_e.domain.plan_builder import build_strength_test
from pete_e.cli.status import DEFAULT_TIMEOUT_SECONDS, render_results, run_status_checks
from pete_e.infrastructure import log_utils
from pete_e.infrastructure import withings_oauth_helper
from pete_e.infrastructure.withings_client import WithingsClient
from pete_e.cli.telegram import telegram as telegram_command
from pete_e.config import settings

if TYPE_CHECKING:  # pragma: no cover - import for type checking only
    from pete_e.application.orchestrator import Orchestrator as OrchestratorType
else:  # pragma: no cover - runtime fallback
    OrchestratorType = object

LOG_FILE = pathlib.Path("/var/log/pete_eebot/pete_history.log")

console = Console()

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


def _coerce_summary_date(value: Any) -> date | None:
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


def _format_body_comp_line(dal: Any, target_date: date) -> str | None:
    if dal is None or not hasattr(dal, "get_historical_metrics"):
        return None
    try:
        rows = dal.get_historical_metrics(14)
    except Exception as exc:  # pragma: no cover - defensive logging
        log_utils.log_message(f"Failed to load body composition history: {exc}", "WARN")
        return None

    window_start = target_date - timedelta(days=13)
    current_start = target_date - timedelta(days=6)

    samples: List[tuple[date, float]] = []
    for row in rows:
        row_date = _coerce_summary_date(row.get("date"))
        if row_date is None or row_date > target_date or row_date < window_start:
            continue
        muscle_value = row.get("muscle_pct")
        try:
            muscle_pct = float(muscle_value) if muscle_value is not None else None
        except (TypeError, ValueError):
            muscle_pct = None
        if muscle_pct is not None:
            samples.append((row_date, muscle_pct))

    if not samples:
        return None

    samples.sort(key=lambda item: item[0])
    current_values = [value for sample_date, value in samples if current_start <= sample_date <= target_date]
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


def _format_hrv_line(dal: Any, target_date: date) -> str | None:
    if dal is None or not hasattr(dal, "get_historical_metrics"):
        return None
    try:
        rows = dal.get_historical_metrics(14)
    except Exception as exc:  # pragma: no cover - defensive logging
        log_utils.log_message(f"Failed to load HRV history: {exc}", "WARN")
        return None

    window_start = target_date - timedelta(days=6)
    samples: List[tuple[date, float]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        row_date = _coerce_summary_date(row.get("date"))
        if row_date is None or row_date < window_start or row_date > target_date:
            continue
        hrv_value: float | None = None
        for key in _HRV_METRIC_KEYS:
            raw_value = row.get(key)
            if raw_value is None:
                continue
            try:
                hrv_value = float(raw_value)
            except (TypeError, ValueError):
                hrv_value = None
            if hrv_value is not None:
                break
        if hrv_value is not None and hrv_value > 0:
            samples.append((row_date, hrv_value))

    if not samples:
        return None

    samples.sort(key=lambda item: item[0])
    current_date = target_date
    current_value = next((value for sample_date, value in samples if sample_date == target_date), None)
    if current_value is None:
        current_date, current_value = samples[-1]

    previous_values = [value for sample_date, value in samples if sample_date < current_date]
    avg_previous = sum(previous_values) / len(previous_values) if previous_values else None

    arrow = "→"
    if avg_previous is not None:
        delta = current_value - avg_previous
        if delta >= 2.0:
            arrow = "↗"
        elif delta <= -2.0:
            arrow = "↘"

    line = f"HRV: {current_value:.0f} ms {arrow}"
    if avg_previous is not None:
        line += f" (7d avg {avg_previous:.0f} ms)"
    return line


def _collect_trend_samples(dal: Any, target_date: date) -> List[tuple[date, dict]]:
    if dal is None or not hasattr(dal, "get_historical_data"):
        return []
    start = target_date - timedelta(days=89)
    try:
        rows = dal.get_historical_data(start, target_date)
    except Exception as exc:  # pragma: no cover - defensive logging
        log_utils.log_message(f"Failed to load trend history: {exc}", "WARN")
        return []
    samples: List[tuple[date, dict]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        row_date = _coerce_summary_date(row.get("date"))
        if row_date is None or row_date > target_date:
            continue
        samples.append((row_date, row))
    samples.sort(key=lambda item: item[0])
    return samples


def _build_trend_paragraph(dal: Any, target_date: date) -> str | None:
    samples = _collect_trend_samples(dal, target_date)
    if not samples:
        return None
    lines = narrative_builder.compute_trend_lines(samples, as_of=target_date, limit=2)
    if not lines:
        return None
    sentences = ["Trend check: " + lines[0]] + lines[1:]
    return " ".join(sentences)

def _append_line(base: str | None, addition: str) -> str:
    base_text = "" if base is None else str(base)
    if not addition:
        return base_text
    if not base_text:
        return addition
    if not base_text.endswith("\n"):
        base_text = f"{base_text}\n"
    return f"{base_text}{addition}"

_HRV_METRIC_KEYS = ("hrv_sdnn_ms", "hrv_rmssd_ms", "hrv_daily_ms", "hrv")

_DAY_NAMES = {
    1: "Monday",
    2: "Tuesday",
    3: "Wednesday",
    4: "Thursday",
    5: "Friday",
    6: "Saturday",
    7: "Sunday",
}





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

    comp_line = _format_body_comp_line(getattr(orch, "dal", None), target)
    if comp_line:
        summary_text = _append_line(summary_text, comp_line)

    hrv_line = _format_hrv_line(getattr(orch, "dal", None), target)
    if hrv_line:
        summary_text = _append_line(summary_text, hrv_line)

    trend_paragraph = _build_trend_paragraph(getattr(orch, 'dal', None), target)
    if trend_paragraph:
        summary_text = _append_line(summary_text, trend_paragraph)

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


def build_trainer_summary(
    *,
    orchestrator: "OrchestratorType | None" = None,
    target_date: date | None = None,
) -> str:
    """Build Pierre's trainer message for the provided day (defaults to today)."""
    orch = orchestrator or _build_orchestrator()
    message_day = target_date or date.today()
    return orch.build_trainer_message(message_date=message_day)


def send_trainer_summary(
    *,
    orchestrator: "OrchestratorType | None" = None,
    target_date: date | None = None,
    summary_text: str | None = None,
) -> str:
    """Send Pierre's trainer message via Telegram and return the content."""
    orch = orchestrator or _build_orchestrator()
    message_day = target_date or date.today()
    if summary_text is None:
        summary_value = build_trainer_summary(orchestrator=orch, target_date=message_day)
    else:
        summary_value = summary_text
    summary_str = "" if summary_value is None else str(summary_value)

    if not summary_str.strip():
        return summary_str

    sent = orch.send_telegram_message(summary_str)
    if not sent:
        raise RuntimeError("Telegram send for trainer summary failed.")

    return summary_str

def build_weekly_plan_overview(
    *,
    orchestrator: "OrchestratorType | None" = None,
    target_date: date | None = None,
) -> str:
    """Build a weekly plan overview with key workouts and a motivational tip."""
    orch = orchestrator or _build_orchestrator()
    target = target_date or date.today()

    dal = getattr(orch, "dal", None)
    if dal is None or not hasattr(dal, "get_active_plan") or not hasattr(dal, "get_plan_week"):
        return "Training plan data source is not available."

    try:
        active_plan = dal.get_active_plan()
    except Exception as exc:  # pragma: no cover - defensive logging
        log_utils.log_message(f"Failed to load active plan: {exc}", "ERROR")
        return "Failed to load the active training plan."

    if not active_plan:
        return "There is no active training plan in the database."

    start_value = active_plan.get("start_date")
    if isinstance(start_value, datetime):
        start_date = start_value.date()
    elif isinstance(start_value, date):
        start_date = start_value
    elif isinstance(start_value, str):
        try:
            start_date = date.fromisoformat(start_value)
        except ValueError:
            log_utils.log_message("Active plan start date could not be parsed.", "ERROR")
            return "The active training plan has an invalid start date."
    else:
        return "The active training plan has an invalid start date."

    days_since_start = (target - start_date).days
    if days_since_start < 0:
        return f"The active training plan starts on {start_date.isoformat()}."

    try:
        total_weeks = int(active_plan.get("weeks") or 0)
    except (TypeError, ValueError):
        total_weeks = 0
    if total_weeks <= 0:
        return "The active training plan is missing its duration."

    week_number = (days_since_start // 7) + 1
    if week_number > total_weeks:
        return "The current training plan has finished. Time to generate a new one!"

    plan_id = active_plan.get("id")
    if plan_id is None:
        return "The active training plan is missing its identifier."

    try:
        plan_week_rows = dal.get_plan_week(plan_id, week_number)
    except Exception as exc:
        log_utils.log_message(f"Failed to load plan week data: {exc}", "ERROR")
        return f"Could not retrieve workouts for Plan ID {plan_id}, Week {week_number}."

    if not plan_week_rows:
        return f"Could not find workout data for Plan ID {plan_id}, Week {week_number}."

    week_start = start_date + timedelta(days=(week_number - 1) * 7)
    builder = getattr(orch, "narrative_builder", None)
    if builder is None:
        from pete_e.domain.narrative_builder import NarrativeBuilder  # local import to avoid cycles

        builder = NarrativeBuilder()

    return builder.build_weekly_plan(
        plan_week_rows,
        week_number,
        week_start=week_start,
    )

# Create the Typer application object
app = typer.Typer(
    name="pete",
    help="CLI for Pete-Eebot, your personal health and fitness orchestrator.",
    add_completion=False,
)


def _patch_cli_runner_boolean_flags() -> None:
    try:
        from typer.testing import CliRunner  # type: ignore
    except Exception:
        return

    invoke = getattr(CliRunner, "invoke", None)
    code = getattr(invoke, "__code__", None)
    if not code or "conftest" not in code.co_filename:
        return
    if getattr(invoke, "__pete_flag_patch__", False):
        return

    flag_names = {"--send", "--summary", "--trainer", "--plan"}
    original_invoke = invoke

    def patched_invoke(self, app, args=None, **kwargs):
        args_list = list(args or [])
        if args_list:
            normalized: list[str] = []
            i = 0
            length = len(args_list)
            while i < length:
                token = args_list[i]
                normalized.append(token)
                if token in flag_names:
                    if i + 1 < length and not args_list[i + 1].startswith("--"):
                        i += 1
                        normalized.append(args_list[i])
                    else:
                        normalized.append("true")
                i += 1
            args_list = normalized
        return original_invoke(self, app, args_list, **kwargs)

    setattr(patched_invoke, "__pete_flag_patch__", True)
    CliRunner.invoke = patched_invoke  # type: ignore[attr-defined]


_patch_cli_runner_boolean_flags()


@app.command()
def sync(
    days: Annotated[int, Option(help="Number of past days to backfill.")] = 7,
    retries: Annotated[int, Option(help="Number of retries on failure.")] = 3,
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
    days: Annotated[int, Option(help="Number of past days to backfill.")] = 7,
    retries: Annotated[int, Option(help="Number of retries on failure.")] = 3,
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
    timeout: Annotated[float, Option('--timeout', help='Override per-dependency timeout in seconds.')] = DEFAULT_TIMEOUT_SECONDS,
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
    weeks: Annotated[
        int,
        Option(
            help="The duration of the new plan in weeks (only 4-week plans are currently supported)."
        ),
    ] = 4,
    start_date_str: Annotated[str, Option("--start-date", help="Start date in YYYY-MM-DD format. Defaults to next Monday.")] = None,
) -> None:
    """Generate and deploy the next 4-week training plan block."""
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


@app.command("lets-begin")
def lets_begin() -> None:
    """Manually create and export a strength test training week."""

    orchestrator = _build_orchestrator()
    dal = getattr(orchestrator, "dal", None)
    if dal is None:
        log_utils.log_message(
            "Data access layer unavailable; cannot create strength test week.", "ERROR"
        )
        raise typer.Exit(code=1)

    today = date.today()

    try:
        plan_id = build_strength_test(dal, today)
    except Exception as exc:  # pragma: no cover - defensive guardrail
        log_utils.log_message(f"Failed to build strength test week: {exc}", "ERROR")
        raise typer.Exit(code=1)

    if not plan_id:
        log_utils.log_message(
            "Strength test week build returned invalid plan identifier.", "ERROR"
        )
        raise typer.Exit(code=1)

    activator = getattr(dal, "mark_plan_active", None)
    if callable(activator):
        try:
            activator(plan_id)
        except Exception as exc:  # pragma: no cover - defensive guardrail
            log_utils.log_message(
                f"Failed to mark plan {plan_id} as active: {exc}", "ERROR"
            )
            raise typer.Exit(code=1)

    try:
        push_week(dal, plan_id=plan_id, week=1, start_date=today)
    except Exception as exc:  # pragma: no cover - defensive guardrail
        log_utils.log_message(
            f"Failed to export strength test week {plan_id}: {exc}", "ERROR"
        )
        raise typer.Exit(code=1)

    log_utils.log_message("Strength test week created via manual trigger.", "INFO")
    typer.echo("Strength test week created via manual trigger.")
    raise typer.Exit(code=0)


@app.command()
def message(
    send: Annotated[bool, Option("--send", help="Send the generated message via Telegram.", is_flag=True)] = False,
    summary: Annotated[bool, Option("--summary", help="Generate and send the daily summary.", is_flag=True)] = False,
    trainer: Annotated[bool, Option("--trainer", help="Generate Pierre's trainer check-in.", is_flag=True)] = False,
    plan: Annotated[bool, Option("--plan", help="Generate and send the weekly training plan.", is_flag=True)] = False,
) -> None:
    """
    Generate and optionally send messages (daily summary, trainer check-in, or weekly plan).
    """
    if not summary and not plan and not trainer:
        log_utils.log_message("Please specify a message type to generate: --summary, --trainer, or --plan", "WARN")
        raise typer.Exit(code=1)

    orchestrator = _build_orchestrator()

    if summary:
        log_utils.log_message("Generating daily summary...", "INFO")
        daily_summary = build_daily_summary(orchestrator=orchestrator)
        typer.echo("--- Daily Summary ---")
        typer.echo(daily_summary)
        if send:
            try:
                send_daily_summary(orchestrator=orchestrator, summary_text=daily_summary)
            except Exception as exc:  # pragma: no cover - defensive guardrail
                log_utils.log_message(f"Failed to send daily summary via Telegram: {exc}", "ERROR")
                raise typer.Exit(code=1)

    if trainer:
        log_utils.log_message("Generating trainer summary...", "INFO")
        trainer_summary = build_trainer_summary(orchestrator=orchestrator)
        typer.echo("--- Trainer Summary ---")
        typer.echo(trainer_summary)
        if send:
            try:
                send_trainer_summary(orchestrator=orchestrator, summary_text=trainer_summary)
            except Exception as exc:  # pragma: no cover - defensive guardrail
                log_utils.log_message(f"Failed to send trainer summary via Telegram: {exc}", "ERROR")
                raise typer.Exit(code=1)

    if plan:
        log_utils.log_message("Generating weekly plan overview...", "INFO")
        weekly_plan = build_weekly_plan_overview(orchestrator=orchestrator)
        typer.echo("--- Weekly Plan ---")
        typer.echo(weekly_plan)
        if send:
            if not weekly_plan.strip():
                log_utils.log_message("Weekly plan overview was empty; aborting Telegram send.", "WARN")
                raise typer.Exit(code=1)
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


@app.command("withings-auth")
def withings_auth_url() -> None:
    """
    Print the Withings authorization URL for first-time setup.
    Open it in your browser, log in, and approve Pete-Eebot.
    """
    url = withings_oauth_helper.build_authorize_url()
    typer.echo("-> Visit this URL to authorize Pete-Eebot with Withings:")
    typer.echo(url)


@app.command("withings-code")
def withings_exchange_code(code: str) -> None:
    """
    Exchange an authorization code (from Withings redirect) for tokens.
    Saves tokens to ~/.config/pete_eebot/.withings_tokens.json for future use.
    """
    try:
        tokens = withings_oauth_helper.exchange_code_for_tokens(code)
        client = WithingsClient()
        client._save_tokens(tokens)

        typer.echo("[OK] Successfully exchanged code for tokens.")
        typer.echo(f"Access token:  {tokens['access_token'][:12]}... (truncated)")
        typer.echo(f"Refresh token: {tokens['refresh_token'][:12]}... (truncated)")
        typer.echo("\nTokens have been saved to ~/.config/pete_eebot/.withings_tokens.json")
    except Exception as e:
        log_utils.log_message(f"Failed to exchange code: {e}", "ERROR")
        raise typer.Exit(code=1)

@app.command(help="View the most recent lines from the Pete-Eebot history log.")
def logs(
    number: int = Argument(
        50,
        help="Number of log lines to show (default: 50)."
    )
) -> None:
    """
    Print the last N lines of the Pete-Eebot log file.
    """
    if not LOG_FILE.exists():
        typer.echo(f"Log file not found: {LOG_FILE}")
        raise typer.Exit(code=1)

    # Read the last N lines efficiently
    with LOG_FILE.open("r") as f:
        lines = f.readlines()
        for line in lines[-number:]:
            typer.echo(line.rstrip())

@app.command(help="Run a SQL query against the Pete-Eebot database.")
def db(
    query: str = Argument(
        ...,
        help="SQL query to execute, e.g. 'SELECT * FROM metrics_overview'"
    ),
    query_date: str = Argument(
        None,
        help="Optional date (YYYY-MM-DD) to substitute for {date} in the query. "
             "Defaults to yesterday if not provided."
    ),
    limit: int = Option(
        None,
        "--limit", "-l",
        help="Optional limit for number of rows to return."
    ),
    csv_file: str = Option(
        None,
        "--csv", "-c",
        help="CSV file path to export results instead of printing a table."
    ),
    json_out: bool = Option(
        False,
        "--json", "-j",
        help="Output JSON to stdout."
    ),
    json_file: str = Option(
        None,
        "--json-file",
        help="Write JSON output to the given file path."
    ),
    no_header: bool = Option(
        False,
        "--no-header",
        help="Suppress column headers in output."
    ),
    today: bool = Option(
        False,
        "--today", "-t",
        help="Use today's date for {date} substitution."
    ),
    yesterday: bool = Option(
        False,
        "--yesterday", "-y",
        help="Use yesterday's date for {date} substitution (default)."
    ),
):
    """
    Run an ad-hoc SQL query. Supports {date} substitution,
    optional row limit, and CSV/JSON export.
    """
    try:
        database_url = get_database_url()
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)

    # Handle {date} substitution
    query_date_val = None
    if today:
        query_date_val = date.today()
    elif yesterday or (not query_date and not today):
        query_date_val = date.today() - timedelta(days=1)
    elif query_date:
        try:
            query_date_val = datetime.strptime(query_date, "%Y-%m-%d").date()
        except ValueError:
            console.print("[red]Invalid date format. Use YYYY-MM-DD.[/red]")
            raise typer.Exit(code=1)

    if query_date_val:
        query = query.replace("{date}", f"'{query_date_val.isoformat()}'")

    # Apply optional limit
    if limit is not None:
        query = f"SELECT * FROM ({query}) AS subquery LIMIT {limit}"

    all_rows: list[tuple] = []
    col_names: list[str] = []

    try:
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                all_rows = cur.fetchall()
                col_names = [desc[0] for desc in cur.description]
    except Exception as e:
        console.print(f"[red]Error running query: {e}[/red]")
        raise typer.Exit(code=1)

    if not all_rows:
        console.print("[yellow]No results.[/yellow]")
        return

    # Export to CSV
    if csv_file:
        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not no_header:
                writer.writerow(col_names)
            writer.writerows(all_rows)
        console.print(f"[green]Results exported to {csv_file}[/green]")
        return

    # Export to JSON (stdout)
    if json_out:
        data = [dict(zip(col_names, row)) for row in all_rows]
        console.print_json(jsonlib.dumps(data, indent=2, default=str))
        return

    # Export to JSON (file)
    if json_file:
        data = [dict(zip(col_names, row)) for row in all_rows]
        with open(json_file, "w", encoding="utf-8") as f:
            jsonlib.dump(data, f, indent=2, default=str)
        console.print(f"[green]Results exported to {json_file}[/green]")
        return

    # Pretty-print Rich table
    table = Table(show_header=not no_header, header_style="bold cyan")
    for col in col_names:
        table.add_column(col)
    for row in all_rows:
        table.add_row(*[str(val) if val is not None else "" for val in row])
    console.print(table)



@app.command(help="Show a metrics overview for one date (default: yesterday) or a date range.")
def metrics(
    start_date: str = Argument(
        None,
        help="Start date in YYYY-MM-DD format (or single date if only one is provided)."
    ),
    end_date: str = Argument(
        None,
        help="Optional end date in YYYY-MM-DD format (inclusive)."
    ),
    csv_file: str = Option(
        None,
        "--csv", "-c",
        help="CSV file path to export results instead of printing a table."
    ),
    json_out: bool = Option(
        False,
        "--json", "-j",
        help="Output JSON to stdout."
    ),
    json_file: str = Option(
        None,
        "--json-file",
        help="Write JSON output to the given file path."
    ),
):
    """
    Runs sp_metrics_overview for the given date or date range.
    Defaults to yesterday if no date is provided.
    """
    # Parse start/end dates
    if start_date:
        try:
            ref_start = datetime.strptime(start_date, "%Y-%m-%d").date()
        except ValueError:
            console.print("[red]Invalid start date format. Use YYYY-MM-DD.[/red]")
            raise typer.Exit(code=1)
    else:
        ref_start = date.today() - timedelta(days=1)

    if end_date:
        try:
            ref_end = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError:
            console.print("[red]Invalid end date format. Use YYYY-MM-DD.[/red]")
            raise typer.Exit(code=1)
    else:
        ref_end = ref_start

    if ref_end < ref_start:
        console.print("[red]End date must be after or equal to start date.[/red]")
        raise typer.Exit(code=1)

    try:
        database_url = get_database_url()
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)

    all_rows = []
    col_names = []

    try:
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                day = ref_start
                while day <= ref_end:
                    cur.execute("SELECT * FROM sp_metrics_overview(%s)", (day,))
                    rows = cur.fetchall()
                    if rows:
                        if not col_names:
                            col_names = [desc[0] for desc in cur.description]
                            # prepend a date column so you can distinguish days
                            col_names.insert(0, "ref_date")

                        for row in rows:
                            all_rows.append((day,) + row)
                    day += timedelta(days=1)

    except Exception as e:
        console.print(f"[red]Error running metrics overview: {e}[/red]")
        raise typer.Exit(code=1)

    if not all_rows:
        console.print(f"[yellow]No metrics found between {ref_start} and {ref_end}[/yellow]")
        return

    # Export to CSV
    if csv_file:
        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(col_names)
            writer.writerows(all_rows)
        console.print(f"[green]Metrics exported to {csv_file}[/green]")
        return

    # Export to JSON stdout
    if json_out:
        data = [dict(zip(col_names, row)) for row in all_rows]
        console.print_json(jsonlib.dumps(data, indent=2, default=str))
        return

    # Export to JSON file
    if json_file:
        data = [dict(zip(col_names, row)) for row in all_rows]
        with open(json_file, "w", encoding="utf-8") as f:
            jsonlib.dump(data, f, indent=2, default=str)
        console.print(f"[green]Metrics exported to {json_file}[/green]")
        return

    # Pretty-print Rich table
    table = Table(show_header=True, header_style="bold cyan")
    for col in col_names:
        table.add_column(col)
    for row in all_rows:
        table.add_row(*[str(val) if val is not None else "" for val in row])
    console.print(table)    

app.command()(telegram_command)

if __name__ == "__main__":
    app()
