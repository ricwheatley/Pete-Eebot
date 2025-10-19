"""Utility helpers for writing Pete's logs with rotation and tagging support."""

from __future__ import annotations

import logging
import inspect
from typing import Dict
from pete_e.logging_setup import get_logger, get_tag_for_module

_LEVEL_MAP: Dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
    "PLAN": logging.INFO,
}


def log_message(msg: str, level: str = "INFO", tag: str | None = None, **kwargs) -> None:
    """
    Log a message to Pete's rotating history log with optional tagging.

    Accepts **kwargs for compatibility with standard logging arguments
    like exc_info=True, stacklevel=2, etc.
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

    # 🧠 forward kwargs (e.g., exc_info)
    logger.log(numeric_level, msg, **kwargs)


# ----------------------------------------------------------------------
# Convenience wrappers – all forward **kwargs for flexibility
# ----------------------------------------------------------------------

def debug(msg: str, tag: str | None = None, **kwargs):
    log_message(msg, level="DEBUG", tag=tag, **kwargs)


def info(msg: str, tag: str | None = None, **kwargs):
    log_message(msg, level="INFO", tag=tag, **kwargs)


def warn(msg: str, tag: str | None = None, **kwargs):
    log_message(msg, level="WARNING", tag=tag, **kwargs)


def error(msg: str, tag: str | None = None, **kwargs):
    log_message(msg, level="ERROR", tag=tag, **kwargs)


def critical(msg: str, tag: str | None = None, **kwargs):
    log_message(msg, level="CRITICAL", tag=tag, **kwargs)
