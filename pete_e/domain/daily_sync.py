"""Domain-level orchestration for daily data synchronisation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class AppleHealthImportSummary:
    """Light-weight summary of an Apple Health ingest run."""

    sources: Sequence[str]
    workouts: int
    daily_points: int
    hr_days: int
    sleep_days: int


@dataclass(frozen=True)
class AppleHealthIngestResult:
    """Outcome of importing data from Apple Health."""

    success: bool
    summary: AppleHealthImportSummary | None = None
    failures: Sequence[str] = field(default_factory=tuple)
    statuses: Mapping[str, str] = field(default_factory=dict)
    alerts: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class DailySyncSourceResult:
    """Result of synchronising a single upstream source."""

    success: bool
    failures: Sequence[str] = field(default_factory=tuple)
    statuses: Mapping[str, str] = field(default_factory=dict)
    alerts: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class DailySyncResult:
    """Aggregate result for an entire daily sync run."""

    success: bool
    failures: Sequence[str]
    statuses: Mapping[str, str]
    alerts: Sequence[str]

    def as_tuple(self) -> tuple[bool, Sequence[str], Mapping[str, str], Sequence[str]]:
        """Return the format expected by the CLI retry logic."""

        return (
            self.success,
            list(self.failures),
            dict(self.statuses),
            list(self.alerts),
        )


class WithingsDataSource(Protocol):
    """Minimal contract for loading Withings measurements."""

    def get_summary(self, *, days_back: int) -> Mapping[str, Any] | None:
        """Return a summary for ``days_back`` days in the past."""


class DailyMetricsRepository(Protocol):
    """Persistence operations required for the daily sync."""

    def save_withings_daily(
        self,
        *,
        day: date,
        weight_kg: float | None,
        body_fat_pct: float | None,
        muscle_pct: float | None,
        water_pct: float | None,
    ) -> None:
        """Persist a Withings daily summary."""

    def refresh_daily_summary(self, *, days: int) -> None:
        """Refresh the reporting view that powers the daily summary."""

    def refresh_actual_view(self) -> None:
        """Refresh the supporting view for actual training data."""


class AppleHealthIngestor(Protocol):
    """Contract for components capable of importing Apple Health exports."""

    def ingest(self) -> AppleHealthIngestResult:
        """Run the ingest and return the outcome."""

    def get_last_import_timestamp(self) -> datetime | None:
        """Return the timestamp of the most recent successful import, if known."""


class DailySyncService:
    """Coordinates the daily synchronisation workflow in the domain layer."""

    def __init__(
        self,
        *,
        repository: DailyMetricsRepository,
        withings_source: WithingsDataSource,
        apple_ingestor: AppleHealthIngestor,
    ) -> None:
        self._repository = repository
        self._withings = withings_source
        self._apple = apple_ingestor

    def run_full(self, *, days: int) -> DailySyncResult:
        """Run the full multi-source sync."""

        parts = [
            self._sync_withings(days=days),
            self._ingest_apple(),
            self._refresh_views(days=days, include_actual=True),
        ]
        return self._combine(parts)

    def run_withings_only(self, *, days: int) -> DailySyncResult:
        """Run only the Withings sync and refresh the daily summary."""

        parts = [
            self._sync_withings(days=days),
            self._refresh_views(days=days, include_actual=False),
        ]
        return self._combine(parts)

    def _sync_withings(self, *, days: int) -> DailySyncSourceResult:
        try:
            for offset in range(days):
                summary = self._withings.get_summary(days_back=offset)
                if not summary:
                    continue
                day_value = summary.get("date")
                if not day_value:
                    continue
                day = date.fromisoformat(str(day_value))
                self._repository.save_withings_daily(
                    day=day,
                    weight_kg=summary.get("weight"),
                    body_fat_pct=summary.get("fat_percent"),
                    muscle_pct=summary.get("muscle_percent"),
                    water_pct=summary.get("water_percent"),
                )
        except Exception:
            return DailySyncSourceResult(
                success=False,
                failures=("Withings",),
                statuses={"Withings": "failed"},
                alerts=(),
            )

        return DailySyncSourceResult(
            success=True,
            failures=(),
            statuses={"Withings": "ok"},
            alerts=(),
        )

    def _refresh_views(self, *, days: int, include_actual: bool) -> DailySyncSourceResult:
        try:
            self._repository.refresh_daily_summary(days=days + 1)
            if include_actual:
                self._repository.refresh_actual_view()
        except Exception:
            label = "Database"
            return DailySyncSourceResult(
                success=False,
                failures=(label,),
                statuses={label: "failed"},
                alerts=(),
            )

        label = "Database"
        return DailySyncSourceResult(
            success=True,
            failures=(),
            statuses={label: "ok"},
            alerts=(),
        )

    def _ingest_apple(self) -> AppleHealthIngestResult:
        try:
            return self._apple.ingest()
        except Exception:
            return AppleHealthIngestResult(
                success=False,
                summary=None,
                failures=("Apple Health",),
                statuses={"Apple Health": "failed"},
                alerts=(),
            )

    def _combine(self, parts: Sequence[DailySyncSourceResult | AppleHealthIngestResult]) -> DailySyncResult:
        success = True
        failures: list[str] = []
        statuses: dict[str, str] = {}
        alerts: list[str] = []

        for part in parts:
            success &= part.success
            failures.extend(part.failures)
            statuses.update(part.statuses)
            alerts.extend(part.alerts)

        return DailySyncResult(
            success=success,
            failures=tuple(failures),
            statuses=dict(statuses),
            alerts=tuple(alerts),
        )


__all__ = [
    "AppleHealthImportSummary",
    "AppleHealthIngestResult",
    "AppleHealthIngestor",
    "DailyMetricsRepository",
    "DailySyncResult",
    "DailySyncService",
    "DailySyncSourceResult",
    "WithingsDataSource",
]

