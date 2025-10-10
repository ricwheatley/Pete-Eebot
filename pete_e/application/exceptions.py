"""Custom exception hierarchy for Pete-Eebot application orchestration."""

from __future__ import annotations


class ApplicationError(Exception):
    """Base exception for application orchestration failures."""


class ValidationError(ApplicationError):
    """Raised when weekly validation or calibration cannot be completed."""


class PlanRolloverError(ApplicationError):
    """Raised when cycle rollover or related planning operations fail."""


class DataAccessError(ApplicationError):
    """Raised when persistence layer calls fail during orchestration."""


__all__ = [
    "ApplicationError",
    "ValidationError",
    "PlanRolloverError",
    "DataAccessError",
]
