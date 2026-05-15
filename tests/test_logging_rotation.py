import logging
import json
import sys
from logging.handlers import RotatingFileHandler

import pytest

from pete_e import logging_setup

LOGGER_TAG = "TEST"


@pytest.fixture
def temp_logger(tmp_path):
    log_path = tmp_path / "pete_history.log"
    logging_setup.configure_logging(log_path=log_path, force=True)
    adapter = logging_setup.get_logger(LOGGER_TAG)
    base_logger = logging.getLogger(logging_setup.LOGGER_NAME)
    try:
        yield adapter, base_logger, log_path
    finally:
        logging_setup.reset_logging()
        for handler in list(base_logger.handlers):
            handler.close()
            base_logger.removeHandler(handler)
    """Perform temp logger."""


def test_rotating_handler_defaults(temp_logger):
    adapter, base_logger, log_path = temp_logger
    rotating_handlers = [h for h in base_logger.handlers if isinstance(h, RotatingFileHandler)]
    assert rotating_handlers, 'Expected at least one rotating handler'
    handler = rotating_handlers[0]
    assert handler.maxBytes == logging_setup.DEFAULT_MAX_BYTES
    assert handler.backupCount == logging_setup.DEFAULT_BACKUP_COUNT
    assert handler.baseFilename == str(log_path)
    """Perform test rotating handler defaults."""


def test_rotating_handler_rollover(tmp_path):
    log_path = tmp_path / 'pete_history.log'
    base_logger = logging.getLogger(logging_setup.LOGGER_NAME)
    logging_setup.configure_logging(
        log_path=log_path,
        force=True,
        max_bytes=512,
        backup_count=2,
    )
    adapter = logging_setup.get_logger(LOGGER_TAG)
    try:
        payload = 'x' * 256
        for _ in range(10):
            adapter.info(payload)
        for handler in base_logger.handlers:
            if hasattr(handler, 'flush'):
                handler.flush()
        rolled = log_path.with_name('pete_history.log.1')
        assert log_path.exists()
        assert rolled.exists(), 'Expected first rotated log file to exist'
    finally:
        logging_setup.reset_logging()
        for handler in list(base_logger.handlers):
            handler.close()
            base_logger.removeHandler(handler)
    """Perform test rotating handler rollover."""


def test_console_handler_is_skipped_for_non_interactive_default(tmp_path, monkeypatch):
    log_path = tmp_path / "pete_history.log"
    monkeypatch.delenv("PETE_LOG_TO_CONSOLE", raising=False)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)

    base_logger = logging_setup.configure_logging(log_path=log_path, force=True)
    try:
        stream_handlers = [
            handler
            for handler in base_logger.handlers
            if isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, RotatingFileHandler)
        ]
        assert stream_handlers == []
    finally:
        logging_setup.reset_logging()
    """Perform test console handler is skipped for non interactive default."""


def test_console_handler_can_be_enabled_explicitly(tmp_path, monkeypatch):
    log_path = tmp_path / "pete_history.log"
    monkeypatch.setenv("PETE_LOG_TO_CONSOLE", "true")
    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)

    base_logger = logging_setup.configure_logging(log_path=log_path, force=True)
    try:
        stream_handlers = [
            handler
            for handler in base_logger.handlers
            if isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, RotatingFileHandler)
        ]
        assert len(stream_handlers) == 1
    finally:
        logging_setup.reset_logging()
    """Perform test console handler can be enabled explicitly."""


def test_json_formatter_emits_structured_context(tmp_path):
    log_path = tmp_path / "pete_history.log"
    base_logger = logging_setup.configure_logging(log_path=log_path, force=True)
    try:
        with logging_setup.log_context(request_id="req-1", job_id="sync-abc"):
            logging_setup.get_logger("API").info(
                "GET /status 200",
                extra={"event": "http_request", "outcome": "succeeded", "http_status": 200},
            )
        for handler in base_logger.handlers:
            if hasattr(handler, "flush"):
                handler.flush()

        payload = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
        assert payload["schema_version"] == logging_setup.STRUCTURED_LOG_VERSION
        assert payload["tag"] == "API"
        assert payload["event"] == "http_request"
        assert payload["outcome"] == "succeeded"
        assert payload["request_id"] == "req-1"
        assert payload["job_id"] == "sync-abc"
        assert payload["http_status"] == 200
    finally:
        logging_setup.reset_logging()
