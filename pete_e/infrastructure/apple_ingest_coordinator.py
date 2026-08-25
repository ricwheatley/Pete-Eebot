"""Pure outcome and checkpoint policy for Apple Health Dropbox ingest."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import chain, groupby
from typing import Iterable, Literal, Sequence

from pete_e.domain.daily_sync import AppleHealthIngestFailure


AppleIngestStatus = Literal["ok", "partial", "failed"]


@dataclass(frozen=True)
class AppleIngestSource:
    """One discovered export after timestamp and path normalisation."""

    modified_at: datetime
    path: str


@dataclass(frozen=True)
class AppleTimestampGroup:
    """Discovered files sharing one indivisible checkpoint timestamp."""

    modified_at: datetime
    sources: tuple[AppleIngestSource, ...]


@dataclass(frozen=True)
class AppleFileOutcome:
    """Immutable facts produced by executing one source file."""

    source: AppleIngestSource
    processed: bool
    workouts: int = 0
    daily_points: int = 0
    failure: AppleHealthIngestFailure | None = None


@dataclass(frozen=True)
class AppleTimestampGroupOutcome:
    """Executed outcomes for one equal-timestamp source group."""

    modified_at: datetime
    files: tuple[AppleFileOutcome, ...]


@dataclass(frozen=True)
class AppleIngestDecision:
    """Pure final-result, commit, and safe-checkpoint decision."""

    processed_sources: tuple[str, ...]
    workouts: int
    daily_points: int
    failure_details: tuple[AppleHealthIngestFailure, ...]
    safe_watermark: datetime | None
    checkpoint_to_save: datetime | None
    commit_required: bool
    success: bool
    status: AppleIngestStatus
    source_failures: tuple[str, ...]
    alerts: tuple[str, ...]
    is_no_work: bool


def normalise_timestamp(timestamp: datetime) -> datetime:
    """Return a UTC-aware timestamp using the ingest's legacy naive rule."""

    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def group_discovered_files(
    health_files: Iterable[tuple[datetime, object]],
    workout_files: Iterable[tuple[datetime, object]],
) -> tuple[AppleTimestampGroup, ...]:
    """Merge, normalise, deterministically order, and timestamp-group files."""

    sources = [
        AppleIngestSource(normalise_timestamp(modified_at), str(path))
        for modified_at, path in chain(health_files, workout_files)
    ]
    sources.sort(
        key=lambda source: (source.modified_at, source.path.casefold(), source.path)
    )
    return tuple(
        AppleTimestampGroup(modified_at, tuple(timestamp_sources))
        for modified_at, timestamp_sources in groupby(
            sources,
            key=lambda source: source.modified_at,
        )
    )


def safe_exception_reason(exc: BaseException) -> str:
    """Normalise an exception for the existing operator-visible reason field."""

    reason = " ".join(str(exc).split()) or type(exc).__name__
    return reason[:240]


def normalise_failure_reason(reason: str, *, fallback: str) -> str:
    """Normalise an already classified failure reason with its stage fallback."""

    return " ".join(reason.split())[:240] or fallback


def failure_alert(
    failures: Sequence[AppleHealthIngestFailure],
    *,
    partial: bool,
) -> str:
    """Build the stable single alert for one or more retryable failures."""

    first = failures[0]
    identity = first.file_path or "ingest run"
    outcome = "partially completed" if partial else "failed"
    return (
        f"Apple Health ingest {outcome}; {len(failures)} failure(s) remain retryable. "
        f"First failure: {identity} at {first.stage} ({first.reason})."
    )


def decide_ingest(
    initial_checkpoint: datetime,
    group_outcomes: Iterable[AppleTimestampGroupOutcome],
) -> AppleIngestDecision:
    """Aggregate executed file facts into checkpoint, commit, and result policy."""

    groups = tuple(group_outcomes)
    files = tuple(file for group in groups for file in group.files)
    processed = tuple(file for file in files if file.processed)
    failures = tuple(file.failure for file in files if file.failure is not None)
    safe_watermark = _safe_watermark(initial_checkpoint, groups)
    checkpoint_to_save = safe_watermark if safe_watermark > initial_checkpoint else None
    status = _status(failures, processed)
    partial = status == "partial"
    return AppleIngestDecision(
        processed_sources=tuple(file.source.path for file in processed),
        workouts=sum(file.workouts for file in processed),
        daily_points=sum(file.daily_points for file in processed),
        failure_details=failures,
        safe_watermark=safe_watermark,
        checkpoint_to_save=checkpoint_to_save,
        commit_required=bool(processed) or checkpoint_to_save is not None,
        success=not failures,
        status=status,
        source_failures=("Apple Health",) if failures else (),
        alerts=(failure_alert(failures, partial=partial),) if failures else (),
        is_no_work=not files,
    )


def failed_ingest_decision(
    failure: AppleHealthIngestFailure,
) -> AppleIngestDecision:
    """Return the stable result decision for a transaction-fatal run failure."""

    return AppleIngestDecision(
        processed_sources=(),
        workouts=0,
        daily_points=0,
        failure_details=(failure,),
        safe_watermark=None,
        checkpoint_to_save=None,
        commit_required=False,
        success=False,
        status="failed",
        source_failures=("Apple Health",),
        alerts=(failure_alert((failure,), partial=False),),
        is_no_work=False,
    )


def _safe_watermark(
    initial_checkpoint: datetime,
    groups: Sequence[AppleTimestampGroupOutcome],
) -> datetime:
    safe_watermark = initial_checkpoint
    watermark_blocked = False
    for group in groups:
        if any(file.failure is not None for file in group.files):
            watermark_blocked = True
        elif not watermark_blocked:
            safe_watermark = group.modified_at
    return safe_watermark


def _status(
    failures: Sequence[AppleHealthIngestFailure],
    processed: Sequence[AppleFileOutcome],
) -> AppleIngestStatus:
    if not failures:
        return "ok"
    if processed:
        return "partial"
    return "failed"


__all__ = [
    "AppleFileOutcome",
    "AppleIngestDecision",
    "AppleIngestSource",
    "AppleIngestStatus",
    "AppleTimestampGroup",
    "AppleTimestampGroupOutcome",
    "decide_ingest",
    "failed_ingest_decision",
    "failure_alert",
    "group_discovered_files",
    "normalise_failure_reason",
    "normalise_timestamp",
    "safe_exception_reason",
]
