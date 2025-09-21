"""CLI helpers for Telegram command listening."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, TYPE_CHECKING

import typer
from typing_extensions import Annotated

from pete_e.infrastructure import log_utils

if TYPE_CHECKING:  # pragma: no cover - for typing only
    from pete_e.application.telegram_listener import TelegramCommandListener

_DEFAULT_LIMIT = 5
_DEFAULT_TIMEOUT = 2


def _build_listener(
    *,
    offset_path: Path | None,
    limit: int,
    timeout: int,
) -> "TelegramCommandListener":
    from pete_e.application.telegram_listener import TelegramCommandListener

    return TelegramCommandListener(
        offset_path=offset_path,
        poll_limit=limit,
        poll_timeout=timeout,
    )


def telegram(
    listen_once: Annotated[
        bool,
        typer.Option(
            "--listen-once",
            help="Poll Telegram once for commands and handle supported actions.",
        ),
    ] = False,
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            min=1,
            max=100,
            help="Maximum number of updates to request from Telegram.",
        ),
    ] = _DEFAULT_LIMIT,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            min=0,
            max=30,
            help="Seconds to let Telegram hold the getUpdates request.",
        ),
    ] = _DEFAULT_TIMEOUT,
    offset_path: Annotated[
        Optional[Path],
        typer.Option(
            "--offset-path",
            help="Override the default offset tracking file location.",
        ),
    ] = None,
) -> None:
    """Telegram command utilities."""

    if not listen_once:
        typer.echo("No action requested. Use --listen-once to poll for commands.")
        raise typer.Exit(code=0)

    listener = _build_listener(
        offset_path=offset_path,
        limit=limit,
        timeout=timeout,
    )

    handled = listener.listen_once()
    log_utils.log_message(f"Telegram listener handled {handled} update(s).", "INFO")
    typer.echo(f"Processed {handled} command(s).")

