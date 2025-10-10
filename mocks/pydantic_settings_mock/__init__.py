"""Simplified :mod:`pydantic_settings` replacement for the test environment."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional, Union, get_args, get_origin

from pydantic import FieldInfo, SecretStr


class SettingsConfigDict(dict):
    """Placeholder compatible with the real ``SettingsConfigDict``."""


_MISSING = object()


def _coerce_value(annotation: Any, raw: Any) -> Any:
    if raw is None:
        return None

    origin = get_origin(annotation)
    if origin is Union:
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        if not args:
            return None
        return _coerce_value(args[0], raw)

    if annotation in (Any, None) or annotation is Optional:
        return raw

    if annotation is bool:
        if isinstance(raw, bool):
            return raw
        lowered = str(raw).strip().lower()
        return lowered in {"1", "true", "t", "yes", "on"}

    if annotation is int:
        return int(raw)

    if annotation is float:
        return float(raw)

    if annotation is Path:
        return raw if isinstance(raw, Path) else Path(str(raw))

    if annotation is date:
        return raw if isinstance(raw, date) else date.fromisoformat(str(raw))

    if annotation is SecretStr:
        return raw if isinstance(raw, SecretStr) else SecretStr(raw)

    if annotation is str or annotation is None:
        return str(raw)

    return raw


class BaseSettings:
    """Very small subset of :class:`pydantic_settings.BaseSettings`."""

    model_config: SettingsConfigDict = SettingsConfigDict()

    def __init__(self, **values: Any) -> None:
        annotations: Dict[str, Any] = getattr(type(self), "__annotations__", {})

        for name, annotation in annotations.items():
            if name in values:
                raw_value = values[name]
            else:
                raw_value = self._load_value(name)
            value = _coerce_value(annotation, raw_value)
            setattr(self, name, value)

        self._run_model_validators()

    def _run_model_validators(self) -> None:
        """Execute any validators registered via ``model_validator``."""

        for attribute_name in dir(type(self)):
            attribute = getattr(type(self), attribute_name)
            metadata = getattr(attribute, "__pydantic_model_validator__", None)
            if not callable(attribute) or not metadata:
                continue

            mode = metadata.get("mode")
            if mode in (None, "after"):
                result = attribute(self)
                if result is not None and result is not self:
                    for key, value in vars(result).items():
                        setattr(self, key, value)

    @classmethod
    def _load_value(cls, name: str) -> Any:
        if name in os.environ:
            return os.environ[name]

        default = getattr(cls, name, _MISSING)
        if isinstance(default, FieldInfo):
            return default.default
        if default is not _MISSING:
            return default
        raise ValueError(f"Missing configuration value: {name}")


__all__ = ["BaseSettings", "SettingsConfigDict"]

