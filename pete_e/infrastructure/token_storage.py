"""Infrastructure implementations of token persistence."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Optional

from pete_e.domain.token_storage import TokenStorage
from pete_e.infrastructure.log_utils import log_message


class JsonFileTokenStorage(TokenStorage):
    """Persist tokens to a JSON file on disk."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    def read_tokens(self) -> Optional[Dict[str, object]]:
        if not self._path.exists():
            return None
        try:
            with self._path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception as exc:  # pragma: no cover - defensive logging
            log_message(f"Failed to read tokens from {self._path}: {exc}", "WARN")
            return None

    def save_tokens(self, tokens: Dict[str, object]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as handle:
            json.dump(tokens, handle, indent=2)

        try:
            os.chmod(self._path, 0o600)
        except OSError as exc:  # pragma: no cover - depends on platform
            log_message(f"Could not set permissions on {self._path}: {exc}", "WARN")


__all__ = ["JsonFileTokenStorage"]
