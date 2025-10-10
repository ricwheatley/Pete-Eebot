"""Simplified subset of the :mod:`pydantic` API used in tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Callable


class FieldInfo:
    """Stores metadata about a configured field."""

    def __init__(self, default: Any = None, **kwargs: Dict[str, Any]) -> None:
        self.default = default
        self.metadata = kwargs


def Field(default: Any = None, **kwargs: Dict[str, Any]) -> FieldInfo:
    """Return a lightweight descriptor representing field configuration."""

    return FieldInfo(default=default, **kwargs)


def model_validator(*, mode: str | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that tags a method as a model validator."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        setattr(func, "__pydantic_model_validator__", {"mode": mode or "after"})
        return func

    return decorator


@dataclass
class SecretStr:
    """Minimal drop-in replacement for :class:`pydantic.SecretStr`."""

    _secret_value: str

    def __init__(self, value: Any) -> None:
        object.__setattr__(self, "_secret_value", "" if value is None else str(value))

    def get_secret_value(self) -> str:
        return self._secret_value

    def __str__(self) -> str:  # pragma: no cover - parity with real SecretStr
        return "********"


__all__ = ["Field", "FieldInfo", "SecretStr", "model_validator"]

