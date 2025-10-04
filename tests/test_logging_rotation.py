import logging
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


def test_rotating_handler_defaults(temp_logger):
    adapter, base_logger, log_path = temp_logger
    rotating_handlers = [h for h in base_logger.handlers if isinstance(h, RotatingFileHandler)]
    assert rotating_handlers, 'Expected at least one rotating handler'
    handler = rotating_handlers[0]
    assert handler.maxBytes == logging_setup.DEFAULT_MAX_BYTES
    assert handler.backupCount == logging_setup.DEFAULT_BACKUP_COUNT
    assert handler.baseFilename == str(log_path)


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
