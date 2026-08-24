"""Repair one wger routine from an existing, immutable stored plan week."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Protocol, cast

from pete_e.application.exceptions import ConflictError, NotFoundError, ValidationError
from pete_e.application.services import WgerExportService
from pete_e.infrastructure.postgres_dal import PostgresDal
from pete_e.infrastructure.wger_client import WgerClient


class StoredPlanWeekReader(Protocol):
    """Read/export operations available to the guarded replacement workflow."""

    def get_plan_week_reference(self, week_start: date) -> dict[str, Any] | None: ...

    def get_plan_week_rows(self, plan_id: int, week_number: int) -> list[dict[str, Any]]: ...

    def get_plan_decision_trace(self, plan_id: int, week_number: int) -> list[dict[str, Any]]: ...

    def record_wger_export(
        self,
        plan_id: int,
        week_number: int,
        payload: dict[str, Any],
        response: dict[str, Any] | None = None,
        routine_id: int | None = None,
    ) -> None: ...


@dataclass(frozen=True)
class WgerWeekReplacementResult:
    """Outcome of replacing one wger week from stored plan rows."""

    plan_id: int
    week_number: int
    week_start: date
    routine_id: int
    deleted_existing: bool
    days_sent: int
    success: bool = True

    def summary_line(self) -> str:
        action = "Deleted the existing wger week and resent" if self.deleted_existing else "No wger week was present; sent"
        return (
            f"{action} {self.days_sent} day(s) from stored plan {self.plan_id}, "
            f"week {self.week_number} ({self.week_start.isoformat()})."
        )


class WgerWeekReplacementService:
    """Replace only the external wger week; never generate or update a plan."""

    def __init__(
        self,
        *,
        dal: StoredPlanWeekReader,
        wger_client: WgerClient,
        export_service: WgerExportService | None = None,
    ) -> None:
        self._dal = dal
        self._export_service = export_service or WgerExportService(
            dal=cast(PostgresDal, dal),
            wger_client=wger_client,
        )

    def replace_week(self, week_start: date) -> WgerWeekReplacementResult:
        """Resend the exact stored week after deleting matching wger days, if any."""

        if not isinstance(week_start, date) or week_start.weekday() != 0:
            raise ValidationError(
                "week_start must be a Monday so the stored plan week can be matched exactly.",
                code="invalid_week_start",
            )

        reference = self._dal.get_plan_week_reference(week_start)
        if not reference:
            raise NotFoundError(
                f"No stored plan week starts on {week_start.isoformat()}; nothing was changed in wger.",
                code="stored_plan_week_not_found",
            )

        resolved_week_start = self._coerce_date(reference.get("week_start"))
        if resolved_week_start != week_start:
            raise ConflictError(
                "The stored plan lookup did not return the exact requested week; nothing was changed in wger.",
                code="stored_plan_week_mismatch",
            )

        try:
            plan_id = int(reference["plan_id"])
            week_number = int(reference["week_number"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ConflictError(
                "The stored plan week reference is incomplete; nothing was changed in wger.",
                code="invalid_stored_plan_week",
            ) from exc
        if plan_id < 1 or week_number < 1:
            raise ConflictError(
                "The stored plan week reference is invalid; nothing was changed in wger.",
                code="invalid_stored_plan_week",
            )

        export = self._export_service.replace_stored_plan_week(
            plan_id=plan_id,
            week_number=week_number,
            start_date=week_start,
        )
        return WgerWeekReplacementResult(
            plan_id=plan_id,
            week_number=week_number,
            week_start=week_start,
            routine_id=int(export["routine_id"]),
            deleted_existing=bool(export["deleted_existing"]),
            days_sent=int(export["days"]),
        )

    @staticmethod
    def _coerce_date(value: Any) -> date | None:
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None
        return None


def run_wger_week_replacement(
    *,
    week_start: date,
    dal_factory: Callable[[], PostgresDal] | None = None,
    wger_client_factory: Callable[[], WgerClient] | None = None,
) -> WgerWeekReplacementResult:
    """Composition boundary used by the web operation."""

    dal = (dal_factory or PostgresDal)()
    try:
        service = WgerWeekReplacementService(
            dal=dal,
            wger_client=(wger_client_factory or WgerClient)(),
        )
        return service.replace_week(week_start)
    finally:
        close = getattr(dal, "close", None)
        if callable(close):
            close()


__all__ = [
    "WgerWeekReplacementResult",
    "WgerWeekReplacementService",
    "run_wger_week_replacement",
]
