"""Utility helpers for database connection configuration."""

from __future__ import annotations

import os


def get_database_url() -> str:
    """Return the configured PostgreSQL connection URL.

    Preference is given to the ``DATABASE_URL`` environment variable so that
    command invocations can override configuration at runtime. If it is not
    present, the value constructed from the ``POSTGRES_*`` settings is used.
    A descriptive error is raised if neither source provides a connection
    string, keeping failure modes explicit.
    """

    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url

    from pete_e.config.config import settings

    settings_url = settings.DATABASE_URL
    if settings_url:
        return settings_url

    raise RuntimeError(
        "Database connection information is missing. Set the DATABASE_URL "
        "environment variable or configure the POSTGRES_* variables."
    )
