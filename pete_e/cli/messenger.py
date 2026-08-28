# (Functional) **Command-line interface** (Typer app) exposing main features.

"""
Main Command-Line Interface for the Pete-Eebot application.

This script provides a single entry point for all major operations,
including running the daily data sync, ingesting new data, and sending
notifications.
"""

import os
import uuid
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, List, Optional
try:  # pragma: no cover - optional rich dependency for enhanced CLI output
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text
except ModuleNotFoundError:  # pragma: no cover - fallback for minimal environments
    class Console:  # type: ignore[override]
        """Minimal console shim when ``rich`` is unavailable."""

        def print(self, *args, **kwargs):  # noqa: D401 - mimic ``rich`` signature
            text = " ".join(str(arg) for arg in args)
            print(text)
            """Perform print."""

        def print_json(self, data):
            print(data)
            """Perform print json."""

    class Table:  # type: ignore[override]
        def __init__(self, *columns, **_kwargs):
            self._columns = list(columns)
            self._rows: list[tuple[str, ...]] = []
            """Initialize this object."""

        def add_column(self, column):
            self._columns.append(str(column))
            """Perform add column."""

        def add_row(self, *row):
            self._rows.append(tuple(str(item) for item in row))
            """Perform add row."""

        def __str__(self):
            header = " | ".join(self._columns)
            rows = [" | ".join(row) for row in self._rows]
            body = "\n".join(rows)
            return "\n".join(filter(None, [header, body])) or "(table output unavailable)"
            """Implement the `__str__` dunder method behavior."""
        """Represent Table."""

    class Text:  # type: ignore[override]
        def __init__(self, initial: str | None = None):
            self._parts: list[str] = []
            if initial:
                self._parts.append(str(initial))
            """Initialize this object."""

        def append(self, text, style=None):  # noqa: D401 - match ``rich`` API subset
            self._parts.append(str(text))
            """Perform append."""

        def __str__(self):
            return "".join(self._parts)
            """Implement the `__str__` dunder method behavior."""
        """Represent Text."""

from typing_extensions import Annotated

import typer
import re
import psycopg
import csv
import json as jsonlib

from typer import Argument, Option

from pete_e.infrastructure.db_conn import get_database_url

from pete_e.application.apple_dropbox_ingest import run_apple_health_ingest
from pete_e.application.exceptions import (
    ApplicationError,
    BadRequestError,
    ConflictError,
    DataAccessError,
    NotFoundError,
    PlanRolloverError,
    ValidationError,
)
from pete_e.application.plan_duration import (
    DEFAULT_PLAN_WEEKS,
    PLAN_DURATION_HELP,
    SUPPORTED_PLAN_WEEKS,
    validate_plan_weeks,
)
from pete_e.application.weekly_plan_context import (
    select_compatible_weekly_plan_message_builder,
)
from pete_e.application.daily_summary import (
    HRV_METRIC_KEYS,
    CompatibleDailySummaryMessageBuilder,
    DailySummaryRenderProfile,
    DailySummarySupplementalBuilder,
    append_summary_line,
    coerce_summary_date,
    render_body_age,
)
from pete_e.application.user_service import UserService, normalize_login
from pete_e.application.sync import run_sync_with_retries, run_withings_only_with_retries
from pete_e.application.wger_workout_sync import run_wger_workout_sync
from pete_e.domain import body_age
from pete_e.domain.prescription_validation import PrescriptionValidationError
from pete_e.cli.status import DEFAULT_TIMEOUT_SECONDS, render_results, run_status_checks
from pete_e.infrastructure import log_utils
from pete_e.infrastructure.user_repository import PostgresUserRepository
from pete_e.infrastructure import withings_oauth_helper
from pete_e.infrastructure.apple_health_ingestor import AppleIngestError
from pete_e.infrastructure.withings_client import WithingsClient, configured_withings_token_file
from pete_e.cli.telegram import telegram as telegram_command
from pete_e.config import settings

if TYPE_CHECKING:  # pragma: no cover - import for type checking only
    from pete_e.application.orchestrator import Orchestrator as OrchestratorType
else:  # pragma: no cover - runtime fallback
    OrchestratorType = object


console = Console()


_APPLICATION_EXIT_CODES: dict[type[ApplicationError], int] = {
    ValidationError: 2,
    PlanRolloverError: 3,
    BadRequestError: 2,
    ConflictError: 2,
    NotFoundError: 2,
    DataAccessError: 4,
}


def _echo_error(message: str) -> None:
    typer.secho(message, err=True, fg="red")
    """Perform echo error."""


def _exit_for_application_error(exc: ApplicationError, *, context: str) -> None:
    """Render a friendly error message for application-layer failures."""

    exit_code = next(
        (
            code
            for exc_type, code in _APPLICATION_EXIT_CODES.items()
            if isinstance(exc, exc_type)
        ),
        1,
    )
    log_utils.log_message(f"{context} failed: {exc}", "ERROR")
    _echo_error(f"{context} failed: {exc}")
    raise typer.Exit(code=exit_code)


def _password_from_env_or_prompt(env_name: str) -> str:
    resolved_env_name = str(env_name or "").strip()
    if resolved_env_name:
        password = os.environ.get(resolved_env_name)
        if password is not None:
            return password

    return str(typer.prompt("Owner password", hide_input=True, confirmation_prompt=True))


def _audit_owner_password_reset(
    *,
    outcome: str,
    login: str,
    user=None,
    error: ApplicationError | None = None,
) -> None:
    correlation: dict[str, object] = {"actor": "local_cli"}
    if user is not None:
        correlation.update(
            {
                "target_user_id": getattr(user, "id", None),
                "target_username": getattr(user, "username", None),
                "target_roles": list(getattr(user, "roles", ())),
            }
        )
    summary: dict[str, object] = {
        "target_login": normalize_login(login),
        "method": "local_cli",
        "sessions_revoked": outcome == "succeeded",
    }
    if error is not None:
        summary["error_code"] = error.code

    log_utils.log_checkpoint(
        checkpoint="owner_password_recovery",
        outcome=outcome,
        correlation=correlation,
        summary=summary,
        level="INFO" if outcome == "succeeded" else "WARNING",
        tag="AUDIT",
    )


def _build_orchestrator() -> "OrchestratorType":
    """Lazy import helper to avoid CLI/orchestrator circular dependencies."""
    from pete_e.application.orchestrator import Orchestrator as _Orchestrator
    return _Orchestrator()


def _new_cli_job_id(operation: str) -> str:
    safe_operation = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in operation.lower()).strip("-")
    return f"{safe_operation or 'job'}-cli-{uuid.uuid4().hex[:10]}"


def _run_cli_application_job(
    *,
    operation: str,
    callback,
    request_summary: dict[str, Any],
    result_summary_builder=None,
):
    """Run cron/manual CLI commands through the durable job lock when available."""

    from pete_e.application.jobs import ApplicationJobService
    from pete_e.infrastructure.job_repository import PostgresApplicationJobRepository

    job_id = _new_cli_job_id(operation)
    service = ApplicationJobService(
        PostgresApplicationJobRepository(),
        lease_seconds=settings.PETEEEBOT_JOB_LEASE_SECONDS,
        heartbeat_interval_seconds=settings.PETEEEBOT_JOB_HEARTBEAT_SECONDS,
        recovery_interval_seconds=settings.PETEEEBOT_JOB_RECOVERY_SECONDS,
    )
    try:
        return service.run_callback(
            job_id=job_id,
            operation=operation,
            callback=callback,
            requester=None,
            request_id=job_id,
            correlation_id=job_id,
            request_summary=request_summary,
            timeout_seconds=None,
            auth_scheme="cli",
            result_summary_builder=result_summary_builder,
        )
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        if status_code == 409:
            detail = getattr(exc, "detail", None)
            message = detail.get("message") if isinstance(detail, dict) else str(detail or exc)
            _echo_error(message)
            raise typer.Exit(code=2)
        if isinstance(exc, ApplicationError):
            raise
        log_utils.log_message(
            f"Durable job wrapper failed closed for CLI {operation}: {type(exc).__name__}",
            "ERROR",
        )
        raise
    finally:
        service.close(wait=True)


def _format_body_age_line(trend) -> str | None:
    return render_body_age(trend, DailySummaryRenderProfile.LEGACY_CLI)
    """Perform format body age line."""


def _coerce_summary_date(value: Any) -> date | None:
    return coerce_summary_date(value)
    """Perform coerce summary date."""


def _legacy_summary_warning(message: str) -> None:
    log_utils.log_message(message, "WARN")


def _legacy_body_age_trend(source: object, target_date: date) -> object:
    return body_age.get_body_age_trend(source, target_date=target_date)


def _legacy_supplemental_builder(dal: Any) -> DailySummarySupplementalBuilder:
    return DailySummarySupplementalBuilder(
        dal,
        profile=DailySummaryRenderProfile.LEGACY_CLI,
        warning_sink=_legacy_summary_warning,
        body_age_loader=_legacy_body_age_trend,
    )


def _format_body_comp_line(dal: Any, target_date: date) -> str | None:
    return _legacy_supplemental_builder(dal).format_body_composition_line(
        target_date
    )
    """Perform format body comp line."""


def _format_hrv_line(dal: Any, target_date: date) -> str | None:
    return _legacy_supplemental_builder(dal).format_hrv_line(target_date)
    """Perform format hrv line."""


def _collect_trend_samples(dal: Any, target_date: date) -> List[tuple[date, dict]]:
    return _legacy_supplemental_builder(dal).collect_trend_samples(target_date)
    """Perform collect trend samples."""


def _build_trend_paragraph(dal: Any, target_date: date) -> str | None:
    return _legacy_supplemental_builder(dal).build_trend_paragraph(target_date)
    """Perform build trend paragraph."""

def _append_line(base: str | None, addition: str) -> str:
    return append_summary_line(base, addition)
    """Perform append line."""

_HRV_METRIC_KEYS = HRV_METRIC_KEYS

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
    builder = CompatibleDailySummaryMessageBuilder(
        orch,
        warning_sink=_legacy_summary_warning,
        body_age_loader=_legacy_body_age_trend,
        today=lambda: date.today(),
    )
    return builder.build_daily_summary_message(target_date=target_date)


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
    """Return the application-owned weekly plan message."""
    orch = orchestrator or _build_orchestrator()
    return select_compatible_weekly_plan_message_builder(orch).build_message(
        target_date=target_date,
        current_date=date.today(),
    )


# Create the Typer application object
app = typer.Typer(
    name="pete",
    help="CLI for Pete-Eebot, your personal health and fitness orchestrator.",
    add_completion=False,
)

@app.command("bootstrap-owner")
def bootstrap_owner(
    username: Annotated[
        str,
        Option("--username", "-u", help="Username for the first browser owner account."),
    ] = "",
    email: Annotated[
        Optional[str],
        Option("--email", help="Optional owner email address for browser login."),
    ] = None,
    display_name: Annotated[
        Optional[str],
        Option("--display-name", help="Optional display name shown in the console."),
    ] = None,
    password_env: Annotated[
        str,
        Option(
            "--password-env",
            help="Environment variable containing the new password; prompts securely if unset.",
        ),
    ] = "PETEEEBOT_BOOTSTRAP_OWNER_PASSWORD",
) -> None:
    """Create the first local browser owner account."""

    password = _password_from_env_or_prompt(password_env)
    service = UserService(PostgresUserRepository())
    try:
        user = service.bootstrap_owner(
            username=username,
            email=email,
            display_name=display_name,
            password=password,
        )
    except ApplicationError as exc:
        _exit_for_application_error(exc, context="Owner bootstrap")

    typer.echo(f"Owner user created: {user.username} (id={user.id})")
    typer.echo("Sign in at /login with this username or email.")


@app.command("reset-owner-password")
def reset_owner_password(
    login: Annotated[
        str,
        Option("--login", "-l", help="Existing owner username or email."),
    ] = "",
    password_env: Annotated[
        str,
        Option(
            "--password-env",
            help="Environment variable containing the new password; prompts securely if unset.",
        ),
    ] = "PETEEEBOT_RESET_OWNER_PASSWORD",
) -> None:
    """Reset a local owner password and revoke that owner's browser sessions."""

    password = _password_from_env_or_prompt(password_env)
    service = UserService(PostgresUserRepository())
    try:
        user = service.reset_owner_password(login=login, password=password)
    except ApplicationError as exc:
        _audit_owner_password_reset(outcome="failed", login=login, error=exc)
        _exit_for_application_error(exc, context="Owner password reset")

    _audit_owner_password_reset(outcome="succeeded", login=login, user=user)
    typer.echo(f"Owner password reset: {user.username} (id={user.id})")
    typer.echo("Existing browser sessions for that owner have been revoked.")


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
    try:
        result = _run_cli_application_job(
            operation="sync",
            callback=lambda: run_sync_with_retries(days=days, retries=retries),
            request_summary={"days": days, "retries": retries, "source": "cli"},
            result_summary_builder=lambda sync_result: sync_result.summary_line(days=days),
        )
    except ApplicationError as exc:
        _exit_for_application_error(exc, context="Manual sync")
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
    try:
        result = run_withings_only_with_retries(days=days, retries=retries)
    except ApplicationError as exc:
        _exit_for_application_error(exc, context="Withings-only sync")
    if result.success:
        typer.echo("Withings-only sync completed. Summary written to logs/pete_history.log.")
        raise typer.Exit(code=0)
    typer.echo("Withings-only sync finished with errors. Check logs/pete_history.log for details.")
    raise typer.Exit(code=1)


@app.command(name="wger-sync")
def wger_sync(
    from_date: Annotated[
        Optional[str],
        Option("--from-date", help="First local workout date to reconcile (YYYY-MM-DD)."),
    ] = None,
    to_date: Annotated[
        Optional[str],
        Option("--to-date", help="Last local workout date to reconcile (YYYY-MM-DD)."),
    ] = None,
    dry_run: Annotated[
        bool,
        Option("--dry-run", help="Fetch and validate without changing workout data."),
    ] = False,
) -> None:
    """Reconcile a bounded Wger workout-log window and refresh its read models."""

    def _parse(value: str | None, label: str) -> date | None:
        if value is None:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            _echo_error(f"Invalid {label}: {value}. Use YYYY-MM-DD.")
            raise typer.Exit(code=2)

    resolved_end = _parse(to_date, "--to-date") or date.today()
    resolved_start = _parse(from_date, "--from-date") or (
        resolved_end - timedelta(days=7)
    )
    if resolved_start > resolved_end:
        _echo_error("--from-date must be on or before --to-date.")
        raise typer.Exit(code=2)

    operation = "wger_sync_dry_run" if dry_run else "wger_sync"
    log_utils.log_message(
        (
            f"Starting Wger {'dry run' if dry_run else 'sync'} for "
            f"{resolved_start.isoformat()} through {resolved_end.isoformat()}."
        ),
        "INFO",
    )
    try:
        def callback():
            return run_wger_workout_sync(
                start_date=resolved_start,
                end_date=resolved_end,
                dry_run=dry_run,
            )

        if dry_run:
            result = callback()
        else:
            result = _run_cli_application_job(
                operation=operation,
                callback=callback,
                request_summary={
                    "from_date": resolved_start.isoformat(),
                    "to_date": resolved_end.isoformat(),
                    "dry_run": dry_run,
                    "source": "cli",
                },
                result_summary_builder=lambda sync_result: sync_result.summary_line(),
            )
    except ApplicationError as exc:
        _exit_for_application_error(exc, context="Wger workout sync")
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        log_utils.log_message(f"Wger workout sync failed: {exc}", "ERROR")
        _echo_error(f"Wger workout sync failed: {exc}")
        raise typer.Exit(code=1)

    typer.echo(result.summary_line())
    if result.success:
        raise typer.Exit(code=0)
    raise typer.Exit(code=1)


@app.command()
def status(
    timeout: Annotated[float, Option('--timeout', help='Override per-dependency timeout in seconds.')] = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Quick health check for database and external service integrations."""
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
    except DataAccessError as exc:  # pragma: no cover - defensive guardrail
        _exit_for_application_error(exc, context="Apple Health ingestion")
    except AppleIngestError as exc:  # pragma: no cover - defensive guardrail
        log_utils.log_message(f"Apple Health Dropbox ingestion failed: {exc}", "ERROR")
        _echo_error(f"Apple Health Dropbox ingestion failed: {exc}")
        raise typer.Exit(code=1)

    summary = report.summary
    processed_files = len(summary.sources) if summary else 0
    workouts = summary.workouts if summary else 0
    daily_points = summary.daily_points if summary else 0
    log_utils.log_message(
        (
            "Apple Health Dropbox ingestion finished. "
            f"Processed {processed_files} file(s), "
            f"{workouts} workouts, and {daily_points} metric points."
        ),
        "INFO" if report.success else "ERROR",
    )
    if not report.success:
        for alert in report.alerts:
            _echo_error(str(alert))
        raise typer.Exit(code=1)


@app.command()
def plan(
    weeks: Annotated[
        int,
        Option(
            help=PLAN_DURATION_HELP,
            min=min(SUPPORTED_PLAN_WEEKS),
            max=max(SUPPORTED_PLAN_WEEKS),
        ),
    ] = DEFAULT_PLAN_WEEKS,
    start_date_str: Annotated[str, Option("--start-date", help="Start date in YYYY-MM-DD format. Defaults to next Monday.")] = None,
) -> None:
    """Generate and deploy the next 4-week training plan block."""
    if start_date_str:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    else:
        today = date.today()
        start_date = today + timedelta(days=-today.weekday(), weeks=1)

    try:
        weeks = validate_plan_weeks(weeks)
    except ApplicationError as exc:
        _exit_for_application_error(exc, context="Plan deployment")

    log_utils.log_message("Invoking plan generator...", "INFO")
    orchestrator = _build_orchestrator()

    previous_mode = os.environ.get("PETE_CLI_MODE")
    os.environ["PETE_CLI_MODE"] = "plan"
    plan_id = -1
    try:
        try:
            plan_id = orchestrator.generate_and_deploy_next_plan(start_date=start_date, weeks=weeks)
        except ApplicationError as exc:
            _exit_for_application_error(exc, context="Plan deployment")
    finally:
        if previous_mode is None:
            os.environ.pop("PETE_CLI_MODE", None)
        else:
            os.environ["PETE_CLI_MODE"] = previous_mode
        closer = getattr(orchestrator, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception as exc:  # pragma: no cover - defensive logging
                log_utils.log_message(f"Failed to close plan orchestrator cleanly: {exc}", "WARN")

    if plan_id > 0:
        log_utils.log_message(f"New plan (ID: {plan_id}) deployed successfully!", "INFO")
        raise typer.Exit(code=0)
    log_utils.log_message("Failed to deploy new plan.", "ERROR")
    raise typer.Exit(code=1)


@app.command("repair-plan-targets")
def repair_plan_targets(
    reference_date: Annotated[
        Optional[str],
        Option(
            "--reference-date",
            help="Date whose active-plan week should be republished (YYYY-MM-DD).",
        ),
    ] = None,
    confirmed: Annotated[
        bool,
        Option(
            "--yes",
            help="Confirm the stored-plan repair and Wger week replacement.",
        ),
    ] = False,
) -> None:
    """Repair missing lift targets in the active plan and safely republish Wger."""

    if not confirmed:
        _echo_error("Refusing plan repair without explicit --yes confirmation.")
        raise typer.Exit(code=2)

    try:
        resolved_date = date.fromisoformat(reference_date) if reference_date else date.today()
    except ValueError:
        _echo_error(f"Invalid --reference-date: {reference_date}. Use YYYY-MM-DD.")
        raise typer.Exit(code=2)

    orchestrator = _build_orchestrator()
    try:
        result = _run_cli_application_job(
            operation="repair_plan_targets",
            callback=lambda: orchestrator.repair_active_plan_targets(resolved_date),
            request_summary={
                "reference_date": resolved_date.isoformat(),
                "source": "cli",
            },
            result_summary_builder=lambda repair: (
                f"plan_id={repair.get('plan_id')}, "
                f"workouts_updated={repair.get('workouts_updated', 0)}"
            ),
        )
    except ApplicationError as exc:
        _exit_for_application_error(exc, context="Plan target repair")
    except PrescriptionValidationError as exc:
        log_utils.log_message(f"Plan target repair failed validation: {exc}", "ERROR")
        _echo_error(f"Plan target repair failed validation: {exc}")
        raise typer.Exit(code=2)
    finally:
        closer = getattr(orchestrator, "close", None)
        if callable(closer):
            closer()

    replacement = result.get("replacement") or {}
    typer.echo(
        "Plan target repair completed: "
        f"{result.get('workouts_updated', 0)} workout target(s) repaired; "
        f"Wger routine {replacement.get('routine_id', 'not-required')} published."
    )


@app.command("lets-begin")
def lets_begin(
    start_date: Annotated[
        Optional[str],
        Option(
            "--start-date",
            help="Override the macrocycle start date (YYYY-MM-DD).",
        ),
    ] = None,
) -> None:
    """
    Start a new 13-week 5/3/1 macrocycle and seed the strength test week.
    Uses the Orchestrator’s PlanGenerationService to build and export week 1.
    """
    from pete_e.application.orchestrator import Orchestrator
    from pete_e.infrastructure import log_utils

    # 🧠 Build orchestrator instance
    orchestrator = Orchestrator()

    # 🗓️ Determine start date
    if start_date:
        try:
            resolved_start = date.fromisoformat(start_date)
        except ValueError:
            typer.echo("❌ Invalid start date format. Please use YYYY-MM-DD.", err=True)
            raise typer.Exit(code=1)
    else:
        today = date.today()
        days_until_monday = (0 - today.weekday()) % 7
        resolved_start = today + timedelta(days=days_until_monday)

    typer.echo(f"🚀 Starting new 13-week 5/3/1 macrocycle on {resolved_start:%Y-%m-%d}...")
    log_utils.log_message(
        f"Starting new 13-week 5/3/1 macrocycle on {resolved_start.isoformat()}...",
        "PLAN",
    )

    # 🏗️ Use orchestrator’s PlanGenerationService
    if not callable(getattr(orchestrator, "generate_strength_test_week", None)):
        typer.echo("❌ PlanGenerationService unavailable. Check orchestrator wiring.", err=True)
        raise typer.Exit(code=1)

    try:
        orchestrator.generate_strength_test_week(start_date=resolved_start)
        typer.echo("✅ Strength test week created and exported successfully!")
        log_utils.log_message(
            f"Strength test week created successfully via lets-begin at {resolved_start}",
            "PLAN",
        )
    except Exception as exc:
        log_utils.log_message(f"Failed to build or export plan: {exc}", "ERROR")
        typer.echo(f"❌ Failed to build or export plan: {exc}", err=True)
        raise typer.Exit(code=1)
    finally:
        orchestrator.close()

    typer.echo("🎉 New macrocycle initialized successfully — allez, champion!")
    raise typer.Exit(code=0)



@app.command()
def message(
    send: Annotated[bool, Option("--send", help="Send the generated message via Telegram.")] = False,
    summary: Annotated[bool, Option("--summary", help="Generate and send the daily summary.")] = False,
    trainer: Annotated[bool, Option("--trainer", help="Generate Pierre's trainer check-in.")] = False,
    plan: Annotated[bool, Option("--plan", help="Generate and send the weekly training plan.")] = False,
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


@app.command("morning-report")
def morning_report(
    send: Annotated[
        bool,
        Option("--send", help="Send the morning report via Telegram."),
    ] = False,
    target_date: Annotated[
        Optional[str],
        Option("--date", help="Override the default report date (YYYY-MM-DD)."),
    ] = None,
) -> None:
    """Generate the conversational morning report and optionally send it."""

    orchestrator = _build_orchestrator()

    resolved_date: date | None = None
    if target_date:
        try:
            resolved_date = date.fromisoformat(target_date)
        except ValueError:
            typer.echo(
                "Invalid date supplied to --date. Use YYYY-MM-DD.",
                err=True,
            )
            raise typer.Exit(code=1)

    report = build_daily_summary(orchestrator=orchestrator, target_date=resolved_date)
    if not report.strip():
        typer.echo("No morning report is available yet. Give the sync a minute.")
        raise typer.Exit(code=0)

    typer.echo("--- Morning Report ---")
    typer.echo(report)

    if send:
        try:
            send_daily_summary(orchestrator=orchestrator, summary_text=report)
        except Exception as exc:  # pragma: no cover - defensive guardrail
            log_utils.log_message(f"Failed to send morning report via Telegram: {exc}", "ERROR")
            raise typer.Exit(code=1)

@app.command("refresh-withings")
def refresh_withings_tokens() -> None:
    """
    Force a Withings token refresh and save the new tokens to disk.
    """
    try:
        client = WithingsClient()
        client._refresh_access_token()
        typer.echo("[OK] Withings tokens refreshed.")
        typer.echo(f"Tokens were saved to {configured_withings_token_file()} and are not displayed.")
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
def withings_exchange_code(
    code: Optional[str] = Argument(
        None,
        help="Short-lived authorization code. Omit it to use a hidden prompt and keep it out of shell history.",
    ),
) -> None:
    """
    Exchange an authorization code (from Withings redirect) for tokens.
    Saves tokens to the configured Withings token file for future use.
    """
    try:
        if not code:
            code = typer.prompt("Withings authorization code", hide_input=True)
        tokens = withings_oauth_helper.exchange_code_for_tokens(code)
        client = WithingsClient()
        client._save_tokens(tokens)

        typer.echo("[OK] Successfully exchanged code for tokens.")
        typer.echo(f"Tokens were saved to {configured_withings_token_file()} and are not displayed.")
    except Exception as e:
        log_utils.log_message(f"Failed to exchange code: {e}", "ERROR")
        raise typer.Exit(code=1)

@app.command(help="View Pete-Eebot logs with color-coded output and optional tag filtering.")
def logs(
    tag: str = Argument(
        None,
        help="Optional tag to filter by (e.g. HB, SYNC, PLAN). Can also be a number."
    ),
    number: int = Argument(
        50,
        help="Number of log lines to show (default: 50)."
    ),
) -> None:
    """
    Print the last N lines of the Pete-Eebot log file, optionally filtered by tag.

    Examples:
        pete logs               → last 50 lines
        pete logs 200           → last 200 lines
        pete logs HB            → last 50 lines containing [HB]
        pete logs PLAN 100      → last 100 lines containing [PLAN]
    """

    log_file = settings.log_path  # ← this uses your config property

    if not log_file.exists():
        console.print(f"[bold red]❌ Log file not found:[/bold red] {log_file}")
        raise typer.Exit(code=1)

    # Handle case like `pete logs 200`
    if tag and tag.isdigit():
        number = int(tag)
        tag = None

    # Read the file
    with log_file.open("r", encoding="utf-8") as f:
        lines = f.readlines()

    def _json_log_payload(line: str) -> dict[str, Any] | None:
        try:
            payload = jsonlib.loads(line)
        except jsonlib.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    # Filter by tag if specified
    if tag:
        tag_upper = tag.upper()
        filtered = []
        for line in lines:
            payload = _json_log_payload(line)
            if payload is not None:
                if str(payload.get("tag", "")).upper() == tag_upper:
                    filtered.append(line)
                continue
            if f"[{tag_upper}]" in line:
                filtered.append(line)
        display_lines = filtered[-number:]
        console.print(f"\n📜 [bold cyan]Showing last {number} [{tag.upper()}] log lines:[/bold cyan]\n")
    else:
        display_lines = lines[-number:]
        console.print(f"\n📜 [bold cyan]Showing last {number} log lines:[/bold cyan]\n")

    # Regex pattern for parsing logs
    log_pattern = re.compile(
        r"^\[(?P<time>.*?)\]\s+\[(?P<level>.*?)\]\s+\[(?P<tag>.*?)\]\s+(?P<msg>.*)"
    )

    # Color maps
    level_colors = {
        "INFO": "green",
        "WARNING": "yellow",
        "ERROR": "red",
        "CRITICAL": "bold red",
        "DEBUG": "dim cyan",
    }

    tag_colors = {
        "HB": "cyan",
        "SYNC": "bright_blue",
        "PLAN": "magenta",
        "BACKUP": "bright_green",
        "TGRAM": "bright_cyan",
        "APPLE": "yellow",
        "SYS": "white",
        "GEN": "dim",
    }

    # Print the logs with style
    for line in display_lines:
        payload = _json_log_payload(line)
        if payload is not None:
            time_str = str(payload.get("timestamp", ""))
            level = str(payload.get("level", "INFO")).upper()
            tag_str = str(payload.get("tag", "GEN")).upper()
            msg = str(payload.get("message", ""))
            level_color = level_colors.get(level, "white")
            tag_color = tag_colors.get(tag_str, "dim")

            text = Text()
            text.append(f"[{time_str}] ", style="dim")
            text.append(f"[{level}] ", style=f"bold {level_color}")
            text.append(f"[{tag_str}] ", style=f"bold {tag_color}")
            text.append(msg, style="white")
            extras = [
                f"{field}={payload[field]}"
                for field in ("request_id", "job_id", "outcome", "http_status", "duration_ms")
                if payload.get(field) is not None
            ]
            if extras:
                text.append(" " + " ".join(extras), style="dim")
            console.print(text)
            continue

        match = log_pattern.match(line)
        if not match:
            console.print(line.rstrip())
            continue

        time_str = match.group("time")
        level = match.group("level").upper()
        tag_str = match.group("tag").upper()
        msg = match.group("msg")

        level_color = level_colors.get(level, "white")
        tag_color = tag_colors.get(tag_str, "dim")

        text = Text()
        text.append(f"[{time_str}] ", style="dim")
        text.append(f"[{level}] ", style=f"bold {level_color}")
        text.append(f"[{tag_str}] ", style=f"bold {tag_color}")
        text.append(msg, style="white")

        console.print(text)

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
