# pete_e/infrastructure/database.py

from contextlib import contextmanager

import psycopg

from pete_e.config.config import settings

# British English comments and docstrings.

@contextmanager
def get_conn():
    """
    Provides a managed database connection.
    For higher volume applications, this could be swapped for a connection pool.
    """
    # Use autocommit=False to ensure that transactions are managed explicitly.
    with psycopg.connect(settings.DATABASE_URL, autocommit=False) as conn:
        yield conn
