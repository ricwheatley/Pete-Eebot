"""Application entry point for the Apple Health Dropbox ingest."""

from __future__ import annotations

from typing import Optional

from pete_e.domain.daily_sync import (
    AppleHealthImportSummary,
    AppleHealthIngestResult,
    AppleHealthIngestor,
)
from pete_e.infrastructure.apple_health_ingestor import AppleIngestError, _get_json_from_content
from pete_e.infrastructure.di_container import Container, get_container

__all__ = [
    "AppleHealthImportSummary",
    "AppleHealthIngestResult",
    "AppleHealthIngestor",
    "AppleIngestError",
    "run_apple_health_ingest",
    "get_last_successful_import_timestamp",
    "_get_json_from_content",
]


def _resolve_ingestor(container: Container | None = None) -> AppleHealthIngestor:
    resolved_container = container or get_container()
    return resolved_container.resolve(AppleHealthIngestor)  # type: ignore[arg-type]


def run_apple_health_ingest(
    *,
    container: Container | None = None,
    ingestor: Optional[AppleHealthIngestor] = None,
) -> AppleHealthIngestResult:
    """Execute the Apple Health ingest using dependency-injected collaborators."""

    ingestor = ingestor or _resolve_ingestor(container)
    return ingestor.ingest()


def get_last_successful_import_timestamp(
    *,
    container: Container | None = None,
    ingestor: Optional[AppleHealthIngestor] = None,
):
    """Read the checkpoint stored by the ingest workflow."""

    ingestor = ingestor or _resolve_ingestor(container)
    return ingestor.get_last_import_timestamp()


if __name__ == "__main__":
    try:
        outcome = run_apple_health_ingest()
    except AppleIngestError as exc:  # pragma: no cover - CLI convenience
        from pete_e.infrastructure import log_utils

        log_utils.error(f"Import failed: {exc}")
        raise SystemExit(1)

    from pete_e.infrastructure import log_utils

    summary = outcome.summary
    if summary is None:
        log_utils.info("Import completed with no summary available.")
    else:
        log_utils.info("--- Import Summary ---")
        log_utils.info(f"Source files: {', '.join(summary.sources)}")
        log_utils.info(f"Workouts:     {summary.workouts}")
        log_utils.info(f"Metric points: {summary.daily_points}")
        log_utils.info(f"HR days:      {summary.hr_days}")
        log_utils.info(f"Sleep days:   {summary.sleep_days}")
        log_utils.info("Import complete.")

