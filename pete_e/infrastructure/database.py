# pete_e/infrastructure/database.py

from contextlib import contextmanager

import psycopg

from pete_e.infrastructure.db_conn import get_database_url

# British English comments and docstrings.


@contextmanager
def get_conn():
    """
    Provides a managed database connection.
    For higher volume applications, this could be swapped for a connection pool.
    """
    # Use autocommit=False to ensure that transactions are managed explicitly.
    db_url = get_database_url()
    with psycopg.connect(db_url, autocommit=False) as conn:
        yield conn
