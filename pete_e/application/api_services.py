"""Application services powering the public API endpoints."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict

from pete_e.infrastructure.postgres_dal import PostgresDal


class _DateParserMixin:
    """Shared helpers for services that accept ISO date strings."""

    @staticmethod
    def _parse_iso_date(value: str, field: str) -> date:
        try:
            return date.fromisoformat(value)
        except ValueError as exc:  # pragma: no cover - defensive re-raise
            raise ValueError(f"Invalid date value for '{field}': {value}") from exc


class MetricsService(_DateParserMixin):
    """Read-only service exposing metrics related stored procedures."""

    def __init__(self, dal: PostgresDal):
        self._dal = dal

    def overview(self, iso_date: str) -> Dict[str, Any]:
        target_date = self._parse_iso_date(iso_date, "date")
        columns, rows = self._dal.get_metrics_overview(target_date)
        return {"columns": columns, "rows": rows}


class PlanService(_DateParserMixin):
    """Service for read-only access to stored plan snapshots."""

    def __init__(self, dal: PostgresDal):
        self._dal = dal

    def for_day(self, iso_date: str) -> Dict[str, Any]:
        target_date = self._parse_iso_date(iso_date, "date")
        columns, rows = self._dal.get_plan_for_day(target_date)
        return {"columns": columns, "rows": rows}

    def for_week(self, iso_start_date: str) -> Dict[str, Any]:
        target_date = self._parse_iso_date(iso_start_date, "start_date")
        columns, rows = self._dal.get_plan_for_week(target_date)
        return {"columns": columns, "rows": rows}


class StatusService:
    """Service wrapper for status checks to align with API layers."""

    def __init__(self, dal: PostgresDal):
        self._dal = dal

    def run_checks(self, timeout: float):  # pragma: no cover - integration exercised elsewhere
        # Deferred import to avoid a circular dependency during module import in tests
        from pete_e.cli.status import run_status_checks

        return run_status_checks(timeout=timeout)
