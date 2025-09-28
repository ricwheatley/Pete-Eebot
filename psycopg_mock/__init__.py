"""Minimal fallback implementation of the :mod:`psycopg` package for tests.

This project normally depends on the third-party ``psycopg`` package to build
PostgreSQL connection strings. The automated test environment used here does
not provide that dependency, so this lightweight shim exposes the subset of the
API that the application uses. If the real dependency is installed it will take
precedence on ``PYTHONPATH``, so this module only activates when ``psycopg`` is
absent.
"""

from .conninfo import make_conninfo

__all__ = ["make_conninfo"]

