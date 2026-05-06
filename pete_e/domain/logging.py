"""Lightweight logging helpers for domain code without infrastructure coupling."""
from __future__ import annotations

import logging
from typing import Final

_LEVEL_MAP: Final[dict[str, int]] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _resolve_level(level: str | int) -> int:
    if isinstance(level, int):
        return level
    return _LEVEL_MAP.get(str(level).upper(), logging.INFO)
    """Perform resolve level."""


def log_message(message: str, level: str | int = "INFO") -> None:
    """Log ``message`` using the standard library logger."""

    logging.getLogger("pete_e.domain").log(_resolve_level(level), message)


def debug(message: str) -> None:
    log_message(message, "DEBUG")
    """Perform debug."""


def info(message: str) -> None:
    log_message(message, "INFO")
    """Perform info."""


def warn(message: str) -> None:
    log_message(message, "WARNING")
    """Perform warn."""


def error(message: str) -> None:
    log_message(message, "ERROR")
    """Perform error."""
