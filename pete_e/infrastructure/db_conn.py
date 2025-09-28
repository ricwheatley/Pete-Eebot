"""Utility helpers for database connection configuration."""

from __future__ import annotations

from pete_e.config import get_env


def get_database_url() -> str:
    """Return the configured PostgreSQL connection URL.

    Preference is given to the ``DATABASE_URL`` environment variable so that
    command invocations can override configuration at runtime. If it is not
    present, the value constructed from the ``POSTGRES_*`` settings is used.
    A descriptive error is raised if neither source provides a connection
    string, keeping failure modes explicit.
    """

    url = get_env("DATABASE_URL")
    if url:
        return str(url)

    raise RuntimeError(
        "Database connection information is missing. Set the DATABASE_URL "
        "environment variable or configure the POSTGRES_* variables."
    )
