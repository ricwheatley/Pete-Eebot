"""Domain contracts for importing performed workout sets from wger."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Mapping, Protocol, Sequence


@dataclass(frozen=True)
class WgerWorkoutSet:
    """One normalized performed set from the wger workout log."""

    source_id: str
    session_id: str | None
    performed_at: datetime
    day: date
    exercise_id: int
    set_number: int
    reps: int
    weight_kg: Decimal | None
    rir: float | None


@dataclass(frozen=True)
class WgerWorkoutImportSummary:
    """Counts and date bounds for one bounded wger reconciliation."""

    start_date: date
    end_date: date
    fetched: int
    accepted: int
    skipped: int
    stored: int
    dry_run: bool = False


@dataclass(frozen=True)
class WgerWorkoutIngestResult:
    """Outcome of importing a complete wger workout-log window."""

    success: bool
    summary: WgerWorkoutImportSummary | None = None
    failures: Sequence[str] = field(default_factory=tuple)
    statuses: Mapping[str, str] = field(default_factory=dict)
    alerts: Sequence[str] = field(default_factory=tuple)
    error: str | None = None

    def summary_line(self) -> str:
        """Return a compact operator-facing result line."""

        if self.summary is None:
            return f"Wger sync failed: {self.error or 'unknown error'}"
        summary = self.summary
        mode = "dry-run" if summary.dry_run else "reconciled"
        outcome = "success" if self.success else "failed"
        return (
            f"Wger sync {mode}: {summary.start_date.isoformat()} to "
            f"{summary.end_date.isoformat()} | result={outcome} | fetched={summary.fetched} | "
            f"accepted={summary.accepted} | skipped={summary.skipped} | "
            f"stored={summary.stored}"
        )


class WgerWorkoutIngestor(Protocol):
    """Contract for reconciling a bounded wger workout-log window."""

    def ingest(
        self,
        *,
        start_date: date,
        end_date: date,
        dry_run: bool = False,
    ) -> WgerWorkoutIngestResult:
        """Fetch, validate, and optionally persist the inclusive date range."""


class WgerWorkoutRepository(Protocol):
    """Persistence operations needed by the wger workout ingestor."""

    def validate_wger_exercise_ids(self, exercise_ids: Sequence[int]) -> None:
        """Raise when any remote exercise is absent from the local catalogue."""

    def reconcile_wger_logs(
        self,
        *,
        start_date: date,
        end_date: date,
        workout_sets: Sequence[WgerWorkoutSet],
    ) -> int:
        """Atomically replace the supplied inclusive source window."""


__all__ = [
    "WgerWorkoutImportSummary",
    "WgerWorkoutIngestResult",
    "WgerWorkoutIngestor",
    "WgerWorkoutRepository",
    "WgerWorkoutSet",
]
