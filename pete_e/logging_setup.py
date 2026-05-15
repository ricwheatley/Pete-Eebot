"""Central logging configuration for Pete-Eebot."""

from __future__ import annotations

import contextlib
import contextvars
import datetime as dt
import json
import logging
import os
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
LOG_FORMAT_ENV_VAR = "PETE_LOG_FORMAT"
STRUCTURED_LOG_VERSION = 1
RESERVED_LOG_RECORD_KEYS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "message",
    "module",
    "msecs",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}

_logger: Optional[logging.Logger] = None
_configured: bool = False
_log_context: contextvars.ContextVar[dict[str, object]] = contextvars.ContextVar(
    "pete_log_context",
    default={},
)

class TaggedLogger(logging.LoggerAdapter):
    """Logger adapter that injects a tag field for structured Pete logs."""

    def process(self, msg, kwargs):
        extra = dict(current_log_context())
        extra.update(kwargs.get("extra", {}))
        if "tag" not in extra:
            extra["tag"] = self.extra.get("tag", "GEN")
        kwargs["extra"] = extra
        return msg, kwargs


def current_log_context() -> dict[str, object]:
    """Return the currently bound structured logging context."""

    return dict(_log_context.get())


def bind_log_context(**fields: object) -> contextvars.Token:
    """Merge fields into the active structured logging context."""

    context = current_log_context()
    context.update({key: value for key, value in fields.items() if value is not None})
    return _log_context.set(context)


def reset_log_context(token: contextvars.Token) -> None:
    """Restore a previous logging context token."""

    _log_context.reset(token)


@contextlib.contextmanager
def log_context(**fields: object):
    """Temporarily bind structured fields to all Pete log records."""

    token = bind_log_context(**fields)
    try:
        yield
    finally:
        reset_log_context(token)

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
    """Perform build formatter."""


def _json_default(value: object) -> str:
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    return repr(value)


class JsonLogFormatter(logging.Formatter):
    """Render log records as one compact JSON object per line."""

    def converter(self, timestamp):  # type: ignore[override]
        return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc)

    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.converter(record.created).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        payload: dict[str, object] = {
            "schema_version": STRUCTURED_LOG_VERSION,
            "timestamp": timestamp,
            "level": record.levelname,
            "logger": record.name,
            "tag": getattr(record, "tag", "GEN"),
            "message": record.getMessage(),
        }

        for key, value in record.__dict__.items():
            if key in RESERVED_LOG_RECORD_KEYS or key in payload:
                continue
            if value is None:
                continue
            payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        return json.dumps(payload, default=_json_default, ensure_ascii=False, separators=(",", ":"))


def _build_json_formatter() -> logging.Formatter:
    return JsonLogFormatter()


def _resolve_log_format() -> str:
    candidate = str(get_env(LOG_FORMAT_ENV_VAR, default="json") or "json").strip().lower()
    if candidate in {"json", "text"}:
        return candidate
    print(
        f"Pete logger: unknown log format '{candidate}', defaulting to json.",
        file=sys.stderr,
    )
    return "json"


def _build_configured_formatter() -> logging.Formatter:
    if _resolve_log_format() == "text":
        return _build_formatter()
    return _build_json_formatter()


def _setting_was_provided(name: str) -> bool:
    fields_set = getattr(settings, "model_fields_set", set())
    return name in os.environ or name in fields_set


def _should_log_to_console() -> bool:
    if not _setting_was_provided("PETE_LOG_TO_CONSOLE"):
        return sys.stderr.isatty()

    log_to_console = get_env("PETE_LOG_TO_CONSOLE", default="false")
    return str(log_to_console).lower() in ("true", "1", "yes", "on")


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

    formatter = _build_configured_formatter()
    resolved_path = Path(log_path) if log_path is not None else settings.log_path
    log_path_notice = None
    if log_path is None:
        consume_notice = getattr(settings, "consume_log_path_notice", None)
        if callable(consume_notice):
            log_path_notice = consume_notice()
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

    # Mirror to console by default only for interactive terminals. Cron jobs
    # already append stdout/stderr to the same history log, so console mirroring
    # there creates duplicate log lines.
    if _should_log_to_console():
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    logger.propagate = False

    if log_path_notice:
        logger.warning(log_path_notice, extra={"tag": "SYS"})

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


if __name__ == "__main__":
    # When running this module directly, add a console logger for immediate feedback.
    logger = configure_logging()
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(_build_formatter())
    logger.addHandler(console_handler)
    
    get_logger("SETUP").info("Logging configured with console output for direct execution.")
