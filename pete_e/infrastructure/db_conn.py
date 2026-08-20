"""Utility helpers for database connection configuration."""

from __future__ import annotations

from pete_e.config import settings


def get_database_url() -> str:
    """Return the validated, authoritative PostgreSQL connection string."""

    url = settings.DATABASE_URL
    if url is not None:
        secret_getter = getattr(url, "get_secret_value", None)
        return secret_getter() if callable(secret_getter) else str(url)

    raise RuntimeError(
        "Validated database connection information is unavailable. Recreate "
        "Settings with DATABASE_URL or a complete POSTGRES_* configuration."
    )
