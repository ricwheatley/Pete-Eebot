"""Application entry point for bounded Wger workout reconciliation."""

from __future__ import annotations

from datetime import date

from pete_e.domain.wger_workouts import WgerWorkoutIngestResult, WgerWorkoutIngestor
from pete_e.infrastructure import log_utils
from pete_e.infrastructure.postgres_dal import PostgresDal
from pete_e.infrastructure.wger_client import WgerClient
from pete_e.infrastructure.wger_workout_ingestor import WgerWorkoutLogIngestor


def run_wger_workout_sync(
    *,
    start_date: date,
    end_date: date,
    dry_run: bool = False,
    ingestor: WgerWorkoutIngestor | None = None,
    repository: PostgresDal | None = None,
) -> WgerWorkoutIngestResult:
    """Reconcile Wger sets and refresh their existing downstream read models."""

    owns_repository = repository is None
    resolved_repository = repository or PostgresDal()
    resolved_ingestor = ingestor or WgerWorkoutLogIngestor(
        repository=resolved_repository,
        client=WgerClient(),
    )

    try:
        result = resolved_ingestor.ingest(
            start_date=start_date,
            end_date=end_date,
            dry_run=dry_run,
        )
        if not result.success or dry_run:
            return result

        try:
            resolved_repository.refresh_daily_summary_range(start_date, end_date)
            resolved_repository.refresh_actual_view()
        except Exception as exc:  # noqa: BLE001 - turn refresh failures into operator status
            message = str(exc).strip() or exc.__class__.__name__
            log_utils.error(f"Wger downstream refresh failed: {message}")
            return WgerWorkoutIngestResult(
                success=False,
                summary=result.summary,
                failures=("Database",),
                statuses={"Wger": "ok", "Database": "failed"},
                alerts=(f"Wger data was stored but downstream refresh failed: {message}",),
                error=message,
            )

        return WgerWorkoutIngestResult(
            success=True,
            summary=result.summary,
            statuses={"Wger": "ok", "Database": "ok"},
        )
    finally:
        if owns_repository:
            resolved_repository.close()


__all__ = ["run_wger_workout_sync"]
