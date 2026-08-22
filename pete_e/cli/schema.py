"""Command-line interface for authoritative database schema management."""

from __future__ import annotations

import os
from typing import Annotated

import typer

from pete_e.config import settings
from pete_e.infrastructure.db_conn import get_database_url
from pete_e.infrastructure.schema_migrations import (
    SchemaMigrationError,
    adopt_legacy_reset_database,
    baseline_database,
    format_status,
    inspect_database,
    preflight_upgrade,
    reset_development_database,
    upgrade_database,
    verify_database,
)


app = typer.Typer(
    name="pete-schema",
    help="Inspect, adopt, upgrade, and verify the Pete-Eebot PostgreSQL schema.",
    add_completion=False,
)


def _secret_value(value) -> str | None:
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        return getter()
    return str(value) if value else None


def _runtime_database_url() -> str:
    return get_database_url()


def _migration_database_url() -> str:
    configured = _secret_value(getattr(settings, "PETEEEBOT_MIGRATOR_DATABASE_URL", None))
    return configured or _runtime_database_url()


def _run(command) -> None:
    try:
        status = command()
    except SchemaMigrationError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(format_status(status))


@app.command("status")
def status(
    timeout: Annotated[float, typer.Option(help="Database connection timeout in seconds.")] = 5.0,
) -> None:
    """Inspect ledger state without changing the database."""

    _run(lambda: inspect_database(_runtime_database_url(), timeout=timeout))


@app.command("verify")
def verify(
    timeout: Annotated[float, typer.Option(help="Database connection timeout in seconds.")] = 5.0,
) -> None:
    """Require the runtime database to be at compatible schema head."""

    _run(lambda: verify_database(_runtime_database_url(), timeout=timeout))


@app.command("upgrade")
def upgrade(
    revision: Annotated[
        str,
        typer.Option("--revision", help="Target revision; defaults to authoritative head."),
    ] = "head",
    timeout: Annotated[float, typer.Option(help="Database connection timeout in seconds.")] = 5.0,
) -> None:
    """Transactionally apply pending revisions with the migrator role."""

    _run(
        lambda: upgrade_database(
            _migration_database_url(),
            target_revision=revision,
            timeout=timeout,
        )
    )


@app.command("preflight")
def preflight(
    timeout: Annotated[float, typer.Option(help="Database connection timeout in seconds.")] = 5.0,
) -> None:
    """Refuse untracked, invalid, or incomplete schemas before deployment."""

    _run(lambda: preflight_upgrade(_migration_database_url(), timeout=timeout))


@app.command("baseline")
def baseline(
    revision: Annotated[
        str,
        typer.Option("--revision", help="Last revision already present in the database."),
    ],
    confirm_database: Annotated[
        str,
        typer.Option(
            "--confirm-database",
            help="Exact database name; required to stamp an existing installation.",
        ),
    ],
    timeout: Annotated[float, typer.Option(help="Database connection timeout in seconds.")] = 5.0,
) -> None:
    """Verify and stamp an existing untracked schema without replaying SQL."""

    _run(
        lambda: baseline_database(
            _migration_database_url(),
            revision=revision,
            confirm_database=confirm_database,
            timeout=timeout,
        )
    )


@app.command("adopt-legacy-reset")
def adopt_legacy_reset(
    confirm_database: Annotated[
        str,
        typer.Option(
            "--confirm-database",
            help="Exact database name created from the retired reset snapshot.",
        ),
    ],
    timeout: Annotated[float, typer.Option(help="Database connection timeout in seconds.")] = 5.0,
) -> None:
    """Fingerprint, repair, and ledger the retired non-linear reset snapshot."""

    _run(
        lambda: adopt_legacy_reset_database(
            _migration_database_url(),
            confirm_database=confirm_database,
            timeout=timeout,
        )
    )


@app.command("reset-development")
def reset_development(
    confirm_database: Annotated[
        str,
        typer.Option(
            "--confirm-database",
            help="Exact safe development/test database name to destroy and rebuild.",
        ),
    ],
    i_understand_this_destroys_data: Annotated[
        bool,
        typer.Option(
            "--i-understand-this-destroys-data",
            help="Required explicit acknowledgement; there is no default.",
        ),
    ] = False,
    timeout: Annotated[float, typer.Option(help="Database connection timeout in seconds.")] = 5.0,
) -> None:
    """Destructively rebuild only a confirmed loopback pete_e_dev/test DB."""

    environment = str(getattr(settings, "ENVIRONMENT", "")).strip().lower()
    if environment not in {"dev", "development", "local", "test", "testing"}:
        typer.echo("ERROR: Development reset is disabled outside development/test environments.", err=True)
        raise typer.Exit(code=1)
    if os.getenv("PETEEEBOT_ALLOW_DEVELOPMENT_RESET") != "1":
        typer.echo(
            "ERROR: Set PETEEEBOT_ALLOW_DEVELOPMENT_RESET=1 for this one reset invocation.",
            err=True,
        )
        raise typer.Exit(code=1)

    _run(
        lambda: reset_development_database(
            _migration_database_url(),
            confirm_database=confirm_database,
            destructive_confirmation=i_understand_this_destroys_data,
            timeout=timeout,
        )
    )
    typer.echo("Development/test schema was destroyed and rebuilt from authoritative migrations.")


if __name__ == "__main__":
    app()
