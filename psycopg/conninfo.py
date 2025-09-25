"""Lightweight subset of :mod:`psycopg.conninfo` used in tests."""

from __future__ import annotations

from typing import Any


def _quote(value: Any) -> str:
    text = "" if value is None else str(value)
    escaped = text.replace("\\", "\\\\").replace("'", "\\'")
    needs_quotes = not escaped or any(ch.isspace() for ch in escaped)
    if needs_quotes:
        return f"'{escaped}'"
    return escaped


def make_conninfo(*, user: Any, password: Any, host: Any, port: Any, dbname: Any) -> str:
    """Build a libpq-style connection string.

    This intentionally mirrors the behaviour that the project depends on
    without requiring the external ``psycopg`` package in the test environment.
    The implementation is conservative: all values are converted to strings,
    backslashes and single quotes are escaped, and values containing whitespace
    are quoted.
    """

    parts = [
        f"user={_quote(user)}",
        f"password={_quote(password)}",
        f"host={_quote(host)}",
        f"port={_quote(port)}",
        f"dbname={_quote(dbname)}",
    ]
    return " ".join(parts)

