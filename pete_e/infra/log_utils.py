"""Utility helpers for writing Pete's logs with rotation support."""

from __future__ import annotations

import logging
import sys
import time
from logging.handlers import RotatingFileHandler
from typing import Dict

from pete_e.config import settings


_LOGGER_NAME = "pete_e.history"
_LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_LOG_BACKUP_COUNT = 5
_LEVEL_MAP: Dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _configure_logger() -> logging.Logger:
    """Create a rotating file logger with a console fallback."""

    logger = logging.getLogger(_LOGGER_NAME)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%SZ"
    )
    formatter.converter = time.gmtime  # Use UTC timestamps

    log_file = settings.log_path
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=_LOG_MAX_BYTES,
            backupCount=_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError as exc:  # pragma: no cover - depends on filesystem permissions
        print(
            f"Pete logger: unable to access log file {log_file}: {exc}",
            file=sys.stderr,
        )

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    logger.propagate = False
    return logger


_logger = _configure_logger()


def log_message(msg: str, level: str = "INFO") -> None:
    """Log a message to Pete's rotating history log."""

    level_name = str(level).upper()
    numeric_level = _LEVEL_MAP.get(level_name)

    if numeric_level is None:
        _logger.warning(
            "Received unknown log level '%s'; defaulting to INFO. Message: %s",
            level,
            msg,
        )
        numeric_level = logging.INFO

    _logger.log(numeric_level, msg)
