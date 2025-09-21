"""Utility helpers for writing Pete's logs with rotation support."""

from __future__ import annotations

import logging
from typing import Dict

from pete_e import logging_setup

_LEVEL_MAP: Dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def log_message(msg: str, level: str = "INFO") -> None:
    """Log a message to Pete's rotating history log."""

    logger = logging_setup.get_logger()
    level_name = str(level).upper()
    numeric_level = _LEVEL_MAP.get(level_name)

    if numeric_level is None:
        logger.warning(
            "Received unknown log level '%s'; defaulting to INFO. Message: %s",
            level,
            msg,
        )
        numeric_level = logging.INFO

    logger.log(numeric_level, msg)
