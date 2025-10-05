"""Central logging configuration for Pete-Eebot."""

from __future__ import annotations

import logging
import sys
import time
import inspect
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from pete_e.config import get_env, settings

LOGGER_NAME = "pete_e.history"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024  # 5 MB per log file
DEFAULT_BACKUP_COUNT = 7
LOG_LEVEL_ENV_VAR = "PETE_LOG_LEVEL"

_logger: Optional[logging.Logger] = None
_configured: bool = False

class TaggedLogger(logging.LoggerAdapter):
    """Logger adapter that injects a tag field for structured Pete logs."""

    def process(self, msg, kwargs):
        # If no 'extra' dict was passed, create one
        extra = kwargs.get("extra", {})
        # Insert a default tag if missing
        if "tag" not in extra:
            extra["tag"] = self.extra.get("tag", "GEN")
        kwargs["extra"] = extra
        return msg, kwargs

def _resolve_level(level: Optional[str]) -> int:
    """Translate a textual level into the numeric value logging expects."""

    candidate = str(level or get_env(LOG_LEVEL_ENV_VAR, default=settings.PETE_LOG_LEVEL)).upper()
    numeric_level = logging.getLevelName(candidate)
    if isinstance(numeric_level, int):
        return numeric_level

    print(
        f"Pete logger: unknown log level '{candidate}', defaulting to INFO.",
        file=sys.stderr,
    )
    return logging.INFO


def _build_formatter() -> logging.Formatter:
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(tag)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    formatter.converter = time.gmtime
    return formatter


def configure_logging(
    *,
    log_path: Optional[Path] = None,
    level: Optional[str] = None,
    max_bytes: Optional[int] = None,
    backup_count: Optional[int] = None,
    force: bool = False,
) -> logging.Logger:
    """Ensure the shared logger has a rotating file handler configured."""
    global _logger, _configured
    logger = logging.getLogger(LOGGER_NAME)

    # respect 'force' and explicit log_path arguments
    if _configured and not force and log_path is None:
        if level is not None:
            logger.setLevel(_resolve_level(level))
        return logger

    # clear handlers if forced or previously configured
    if force:
        for h in list(logger.handlers):
            h.close()
            logger.removeHandler(h)
        _configured = False
        _logger = None

    numeric_level = _resolve_level(level)
    logger.setLevel(numeric_level)

    formatter = _build_formatter()
    resolved_path = Path(log_path) if log_path is not None else settings.log_path
    max_bytes = max_bytes or DEFAULT_MAX_BYTES
    backup_count = backup_count or DEFAULT_BACKUP_COUNT

    try:
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            resolved_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError as exc:
        print(
            f"Pete logger: unable to access log file {resolved_path}: {exc}",
            file=sys.stderr,
        )

    # Only add a stream handler if not explicitly disabled.
    log_to_console = get_env("PETE_LOG_TO_CONSOLE", default="true")
    if str(log_to_console).lower() in ("true", "1", "yes", "on"):
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)
    
    logger.propagate = False

    _configured = True
    _logger = logger
    return logger


def get_logger(tag: str | None = None) -> TaggedLogger:
    """Return a tagged Pete logger, configuring it on first access."""
    global _logger, _configured

    # Determine caller module name if no tag given
    if tag is None:
        frame = inspect.stack()[1]
        module = inspect.getmodule(frame[0])
        module_name = getattr(module, "__name__", "unknown")
        tag = get_tag_for_module(module_name)

    base_logger = _logger if _configured and _logger else configure_logging()
    return TaggedLogger(base_logger, {"tag": tag})

# Default tag map per script/module keyword
TAG_MAP = {
    "sync": "SYNC",
    "weekly_calibration": "PLAN",
    "sprint_rollover": "PLAN",
    "heartbeat": "HB",
    "backup": "BACKUP",
    "check_auth": "AUTH",
    "telegram": "TGRAM",
    "dropbox": "APPLE",
    "apple": "APPLE",
    "wger": "WGER",
    "system": "SYS",
    "monitor": "SYS",
}

def get_tag_for_module(module_name: str) -> str:
    """Infer a logging tag from the script or module name."""
    module_name = module_name.lower()
    for key, tag in TAG_MAP.items():
        if key in module_name:
            return tag
    return "GEN"  # fallback

def reset_logging() -> None:
    """Tear down handlers so tests can reconfigure the logger cleanly."""

    global _configured, _logger
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    _configured = False
    _logger = None
