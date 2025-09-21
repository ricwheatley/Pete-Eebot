import logging
from logging.handlers import RotatingFileHandler

import pytest

from pete_e import logging_setup


@pytest.fixture
def temp_logger(tmp_path):
    log_path = tmp_path / 'pete_history.log'
    logger = logging_setup.configure_logging(log_path=log_path, force=True)
    try:
        yield logger, log_path
    finally:
        logging_setup.reset_logging()  # reset to defaults and release handlers
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)


def test_rotating_handler_defaults(temp_logger):
    logger, log_path = temp_logger
    rotating_handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    assert rotating_handlers, 'Expected at least one rotating handler'
    handler = rotating_handlers[0]
    assert handler.maxBytes == logging_setup.DEFAULT_MAX_BYTES
    assert handler.backupCount == logging_setup.DEFAULT_BACKUP_COUNT
    assert handler.baseFilename == str(log_path)


def test_rotating_handler_rollover(tmp_path):
    log_path = tmp_path / 'pete_history.log'
    logger = logging_setup.configure_logging(
        log_path=log_path,
        force=True,
        max_bytes=512,
        backup_count=2,
    )
    try:
        payload = 'x' * 256
        for _ in range(10):
            logger.info(payload)
        for handler in logger.handlers:
            if hasattr(handler, 'flush'):
                handler.flush()
        rolled = log_path.with_name('pete_history.log.1')
        assert log_path.exists()
        assert rolled.exists(), 'Expected first rotated log file to exist'
    finally:
        logging_setup.reset_logging()
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)
