"""Domain-level protocol for persisting OAuth tokens."""

from __future__ import annotations

from typing import Dict, Optional, Protocol


class TokenStorage(Protocol):
    """Abstraction for persisting OAuth token payloads."""

    def read_tokens(self) -> Optional[Dict[str, object]]:
        """Return persisted tokens if available, otherwise ``None``."""

    def save_tokens(self, tokens: Dict[str, object]) -> None:
        """Persist the provided token payload."""


__all__ = ["TokenStorage"]
