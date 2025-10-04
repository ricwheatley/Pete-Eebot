"""Utility helpers for writing Pete's logs with rotation and tagging support."""

from __future__ import annotations

import logging
from typing import Dict
from pete_e.logging_setup import get_logger, get_tag_for_module
import inspect

from pete_e import logging_setup

_LEVEL_MAP: Dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def log_message(msg: str, level: str = "INFO", tag: str | None = None) -> None:
    """
    Log a message to Pete's rotating history log with optional tagging.

    Args:
        msg: Text message to log.
        level: Log level name (INFO, DEBUG, WARNING, ERROR, etc.)
        tag: Optional tag string (e.g. "SYNC", "HB", "TGRAM").
             If not provided, it will be inferred from the calling module.
    """
    # Determine tag if not explicitly provided
    if tag is None:
        frame = inspect.stack()[1]
        module = inspect.getmodule(frame[0])
        module_name = getattr(module, "__name__", "unknown")
        tag = get_tag_for_module(module_name)

    logger = get_logger(tag)

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

# Convenience wrappers
def debug(msg: str, tag: str | None = None):
    log_message(msg, level="DEBUG", tag=tag)

def info(msg: str, tag: str | None = None):
    log_message(msg, level="INFO", tag=tag)

def warn(msg: str, tag: str | None = None):
    log_message(msg, level="WARNING", tag=tag)

def error(msg: str, tag: str | None = None):
    log_message(msg, level="ERROR", tag=tag)

def critical(msg: str, tag: str | None = None):
    log_message(msg, level="CRITICAL", tag=tag)