"""Domain-level orchestration for daily data synchronisation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Mapping, Protocol, Sequence

from pete_e.domain import logging as domain_logging
from pete_e.domain.wger_workouts import WgerWorkoutIngestResult, WgerWorkoutIngestor


WGER_SYNC_WINDOW_DAYS = 8


@dataclass(frozen=True)
class AppleHealthImportSummary:
    """Light-weight summary of an Apple Health ingest run."""

    sources: Sequence[str]
    workouts: int
    daily_points: int
    hr_days: int
    sleep_days: int


@dataclass(frozen=True)
class AppleHealthIngestFailure:
    """Safe, operator-visible detail for one failed ingest stage or file."""

    stage: str
    reason: str
    file_path: str | None = None
    modified_at: datetime | None = None


@dataclass(frozen=True)
class AppleHealthIngestResult:
    """Outcome of importing data from Apple Health.

    ``success`` is true only when every discovered file was safely handled.
    A source status of ``partial`` means some files were committed while at
    least one file remains eligible for replay; ``failed`` means no file from
    the run was committed.
    """

    success: bool
    summary: AppleHealthImportSummary | None = None
    failures: Sequence[str] = field(default_factory=tuple)
    statuses: Mapping[str, str] = field(default_factory=dict)
    alerts: Sequence[str] = field(default_factory=tuple)
    failure_details: Sequence[AppleHealthIngestFailure] = field(default_factory=tuple)


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
        fat_free_mass_kg: float | None = None,
        fat_mass_kg: float | None = None,
        muscle_mass_kg: float | None = None,
        water_mass_kg: float | None = None,
        bone_mass_kg: float | None = None,
        visceral_fat_index: float | None = None,
        bmr_kcal_day: float | None = None,
        nerve_health_score_feet: float | None = None,
        metabolic_age_years: float | None = None,
    ) -> None:
        """Persist a Withings daily summary."""

    def save_withings_measure_groups(
        self,
        *,
        day: date,
        measure_groups: Sequence[Mapping[str, Any]],
    ) -> None:
        """Persist raw Withings measure groups for future-proof analysis."""

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
        wger_ingestor: WgerWorkoutIngestor,
        clock: Callable[[], date] | None = None,
        wger_window_days: int = WGER_SYNC_WINDOW_DAYS,
    ) -> None:
        if wger_window_days < 1:
            raise ValueError("wger_window_days must be at least 1")
        self._repository = repository
        self._withings = withings_source
        self._apple = apple_ingestor
        self._wger = wger_ingestor
        self._clock = clock or date.today
        self._wger_window_days = wger_window_days
        """Initialize this object."""

    def run_full(self, *, days: int) -> DailySyncResult:
        """Run the full multi-source sync."""

        parts: list[DailySyncSourceResult | AppleHealthIngestResult | WgerWorkoutIngestResult] = [
            self._sync_withings(days=days),
            self._ingest_apple(),
        ]
        wger_result = self._ingest_wger()
        parts.append(wger_result)
        if wger_result.success:
            parts.append(
                self._refresh_views(
                    days=days,
                    include_actual=True,
                    minimum_refresh_days=self._wger_window_days - 1,
                )
            )
        else:
            parts.append(
                DailySyncSourceResult(
                    success=True,
                    statuses={"Database": "skipped"},
                )
            )
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
                    fat_free_mass_kg=summary.get("fat_free_mass_kg"),
                    fat_mass_kg=summary.get("fat_mass_kg"),
                    muscle_mass_kg=summary.get("muscle_mass_kg"),
                    water_mass_kg=summary.get("water_mass_kg"),
                    bone_mass_kg=summary.get("bone_mass_kg"),
                    visceral_fat_index=summary.get("visceral_fat_index"),
                    bmr_kcal_day=summary.get("bmr_kcal_day"),
                    nerve_health_score_feet=summary.get("nerve_health_score_feet"),
                    metabolic_age_years=summary.get("metabolic_age_years"),
                )
                self._repository.save_withings_measure_groups(
                    day=day,
                    measure_groups=list(summary.get("measure_groups") or []),
                )
        except Exception as exc:
            domain_logging.log_message(f"Withings sync failed: {exc}", "ERROR")
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
        """Perform sync withings."""

    def _refresh_views(
        self,
        *,
        days: int,
        include_actual: bool,
        minimum_refresh_days: int = 0,
    ) -> DailySyncSourceResult:
        try:
            self._repository.refresh_daily_summary(
                days=max(days + 1, minimum_refresh_days)
            )
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
        """Perform refresh views."""

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
        """Perform ingest apple."""

    def _ingest_wger(self) -> WgerWorkoutIngestResult:
        end_date = self._clock()
        start_date = end_date - timedelta(days=self._wger_window_days - 1)
        try:
            return self._wger.ingest(
                start_date=start_date,
                end_date=end_date,
            )
        except Exception as exc:
            domain_logging.log_message(f"Wger sync failed: {exc}", "ERROR")
            return WgerWorkoutIngestResult(
                success=False,
                failures=("Wger",),
                statuses={"Wger": "failed"},
                alerts=(),
                error=str(exc),
            )

    def _combine(
        self,
        parts: Sequence[
            DailySyncSourceResult | AppleHealthIngestResult | WgerWorkoutIngestResult
        ],
    ) -> DailySyncResult:
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
        """Perform combine."""


__all__ = [
    "AppleHealthIngestFailure",
    "AppleHealthImportSummary",
    "AppleHealthIngestResult",
    "AppleHealthIngestor",
    "DailyMetricsRepository",
    "DailySyncResult",
    "DailySyncService",
    "DailySyncSourceResult",
    "WGER_SYNC_WINDOW_DAYS",
    "WithingsDataSource",
]

