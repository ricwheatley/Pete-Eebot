"""Canonical application error taxonomy used across workflows, services, and API adapters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ApplicationError(Exception):
    """Base exception for all expected application-layer failures."""

    message: str = "Application error"
    code: str = "application_error"
    http_status: int = 500

    def __str__(self) -> str:
        return self.message


class BadRequestError(ApplicationError):
    def __init__(self, message: str, code: str = "bad_request"):
        super().__init__(message=message, code=code, http_status=400)


class UnauthorizedError(ApplicationError):
    def __init__(self, message: str = "Unauthorized", code: str = "unauthorized"):
        super().__init__(message=message, code=code, http_status=401)


class NotFoundError(ApplicationError):
    def __init__(self, message: str = "Resource not found", code: str = "not_found"):
        super().__init__(message=message, code=code, http_status=404)


class ConflictError(ApplicationError):
    def __init__(self, message: str, code: str = "conflict"):
        super().__init__(message=message, code=code, http_status=409)


class ServiceUnavailableError(ApplicationError):
    def __init__(self, message: str, code: str = "service_unavailable"):
        super().__init__(message=message, code=code, http_status=503)


class ValidationError(BadRequestError):
    """Raised when weekly validation or calibration cannot be completed."""

    def __init__(self, message: str, code: str = "validation_failed"):
        super().__init__(message=message, code=code)


class PlanRolloverError(ConflictError):
    """Raised when cycle rollover or related planning operations fail."""

    def __init__(self, message: str, code: str = "plan_rollover_failed"):
        super().__init__(message=message, code=code)


class DataAccessError(ServiceUnavailableError):
    """Raised when persistence layer calls fail during orchestration."""

    def __init__(self, message: str, code: str = "data_access_failed"):
        super().__init__(message=message, code=code)


__all__ = [
    "ApplicationError",
    "BadRequestError",
    "UnauthorizedError",
    "NotFoundError",
    "ConflictError",
    "ServiceUnavailableError",
    "ValidationError",
    "PlanRolloverError",
    "DataAccessError",
]
