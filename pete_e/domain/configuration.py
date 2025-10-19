"""Domain configuration registry decoupled from infrastructure settings."""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class DomainSettings:
    """Runtime configuration values consumed by domain logic."""

    progression_increment: float = 0.05
    progression_decrement: float = 0.05
    rhr_allowed_increase: float = 0.10
    sleep_allowed_decrease: float = 0.85
    hrv_allowed_decrease: float = 0.12
    body_age_allowed_increase: float = 2.0
    global_backoff_factor: float = 0.90
    baseline_days: int = 28
    cycle_days: int = 28
    phrases_path: Optional[Path] = None


_SETTINGS = DomainSettings()


def configure(settings: DomainSettings | None = None, /, **overrides: object) -> None:
    """Override the active :class:`DomainSettings` instance.

    The application layer calls this during bootstrapping with values derived from
    environment configuration. Tests may also override individual fields via
    keyword arguments.
    """

    global _SETTINGS

    if settings is not None and overrides:
        settings = replace(settings, **overrides)
    elif settings is None:
        settings = replace(_SETTINGS, **overrides)

    _SETTINGS = settings


def get_settings() -> DomainSettings:
    """Return the currently configured :class:`DomainSettings`."""

    return _SETTINGS
