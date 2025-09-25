"""Minimal stub of the :mod:`requests` package for offline tests."""

from __future__ import annotations

from typing import Any, Dict


class RequestException(Exception):
    """Base exception class matching the real ``requests`` API."""


class _StubResponse:
    def __init__(self, payload: Dict[str, Any] | None = None, status_code: int = 200):
        self._payload = payload or {"ok": True, "result": []}
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RequestException(f"HTTP {self.status_code}")

    def json(self) -> Dict[str, Any]:
        return self._payload


def post(*args: Any, **kwargs: Any) -> _StubResponse:  # pragma: no cover - fallback
    raise RequestException("HTTP requests are disabled in the test environment")


def get(*args: Any, **kwargs: Any) -> _StubResponse:  # pragma: no cover - fallback
    raise RequestException("HTTP requests are disabled in the test environment")


__all__ = ["RequestException", "post", "get"]

