from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from pete_e.domain.daily_sync import AppleHealthIngestFailure
from pete_e.infrastructure.apple_ingest_coordinator import (
    AppleFileOutcome,
    AppleIngestSource,
    AppleTimestampGroupOutcome,
    decide_ingest,
    failed_ingest_decision,
    failure_alert,
    group_discovered_files,
    normalise_failure_reason,
    normalise_timestamp,
    safe_exception_reason,
)


UTC = timezone.utc
CHECKPOINT = datetime(2024, 1, 1, tzinfo=UTC)


def _source(day: int, path: str) -> AppleIngestSource:
    return AppleIngestSource(datetime(2024, 1, day, tzinfo=UTC), path)


def _success(
    source: AppleIngestSource,
    *,
    workouts: int = 1,
    daily_points: int = 2,
) -> AppleFileOutcome:
    return AppleFileOutcome(
        source=source,
        processed=True,
        workouts=workouts,
        daily_points=daily_points,
    )


def _failure(
    source: AppleIngestSource,
    *,
    processed: bool = False,
    reason: str = "unavailable",
) -> AppleFileOutcome:
    return AppleFileOutcome(
        source=source,
        processed=processed,
        workouts=1 if processed else 0,
        daily_points=2 if processed else 0,
        failure=AppleHealthIngestFailure(
            stage="parse" if processed else "download",
            reason=reason,
            file_path=source.path,
            modified_at=source.modified_at,
        ),
    )


def _group(
    day: int,
    *files: AppleFileOutcome,
) -> AppleTimestampGroupOutcome:
    return AppleTimestampGroupOutcome(
        modified_at=datetime(2024, 1, day, tzinfo=UTC),
        files=tuple(files),
    )


def test_timestamp_normalisation_preserves_legacy_naive_and_aware_rules() -> None:
    naive = datetime(2024, 1, 2, 12)
    plus_one = datetime(2024, 1, 2, 12, tzinfo=timezone(timedelta(hours=1)))

    assert normalise_timestamp(naive) == datetime(2024, 1, 2, 12, tzinfo=UTC)
    assert normalise_timestamp(plus_one) == datetime(2024, 1, 2, 11, tzinfo=UTC)


def test_discovered_files_are_merged_normalised_sorted_and_grouped() -> None:
    noon_naive = datetime(2024, 1, 2, 12)
    noon_utc = datetime(2024, 1, 2, 12, tzinfo=UTC)
    groups = group_discovered_files(
        [(noon_naive, "/z.json"), (noon_utc, "/a.json")],
        [
            (datetime(2024, 1, 2, 13, tzinfo=timezone(timedelta(hours=1))), "/A.json"),
            (datetime(2024, 1, 3, tzinfo=UTC), 42),
        ],
    )

    assert [group.modified_at for group in groups] == [
        datetime(2024, 1, 2, 12, tzinfo=UTC),
        datetime(2024, 1, 3, tzinfo=UTC),
    ]
    assert [source.path for source in groups[0].sources] == [
        "/A.json",
        "/a.json",
        "/z.json",
    ]
    assert groups[1].sources[0].path == "42"


def test_no_work_decision_is_successful_and_side_effect_free() -> None:
    decision = decide_ingest(CHECKPOINT, ())

    assert decision.processed_sources == ()
    assert decision.workouts == 0
    assert decision.daily_points == 0
    assert decision.failure_details == ()
    assert decision.safe_watermark == CHECKPOINT
    assert decision.checkpoint_to_save is None
    assert decision.commit_required is False
    assert decision.success is True
    assert decision.status == "ok"
    assert decision.source_failures == ()
    assert decision.alerts == ()
    assert decision.is_no_work is True


def test_successful_groups_advance_latest_and_aggregate_counts() -> None:
    first = _source(2, "/first.json")
    second = _source(3, "/second.json")

    decision = decide_ingest(
        CHECKPOINT,
        (
            _group(2, _success(first, workouts=2, daily_points=3)),
            _group(3, _success(second, workouts=4, daily_points=5)),
        ),
    )

    assert decision.processed_sources == (first.path, second.path)
    assert decision.workouts == 6
    assert decision.daily_points == 8
    assert decision.safe_watermark == second.modified_at
    assert decision.checkpoint_to_save == second.modified_at
    assert decision.commit_required is True
    assert decision.status == "ok"
    assert decision.is_no_work is False


def test_earlier_failure_blocks_watermark_but_later_success_commits() -> None:
    failed = _source(2, "/failed.json")
    later = _source(3, "/later.json")

    decision = decide_ingest(
        CHECKPOINT,
        (_group(2, _failure(failed)), _group(3, _success(later))),
    )

    assert decision.processed_sources == (later.path,)
    assert decision.safe_watermark == CHECKPOINT
    assert decision.checkpoint_to_save is None
    assert decision.commit_required is True
    assert decision.success is False
    assert decision.status == "partial"
    assert decision.source_failures == ("Apple Health",)
    assert decision.alerts == (
        "Apple Health ingest partially completed; 1 failure(s) remain retryable. "
        "First failure: /failed.json at download (unavailable).",
    )


def test_later_failure_preserves_checkpoint_for_last_safe_group() -> None:
    first = _source(2, "/first.json")
    failed = _source(3, "/failed.json")

    decision = decide_ingest(
        CHECKPOINT,
        (_group(2, _success(first)), _group(3, _failure(failed))),
    )

    assert decision.safe_watermark == first.modified_at
    assert decision.checkpoint_to_save == first.modified_at
    assert decision.commit_required is True
    assert decision.status == "partial"


def test_failed_equal_timestamp_peer_makes_the_whole_group_unsafe() -> None:
    successful_peer = _source(2, "/a.json")
    failed_peer = _source(2, "/b.json")

    decision = decide_ingest(
        CHECKPOINT,
        (_group(2, _success(successful_peer), _failure(failed_peer)),),
    )

    assert decision.processed_sources == (successful_peer.path,)
    assert decision.safe_watermark == CHECKPOINT
    assert decision.checkpoint_to_save is None
    assert decision.status == "partial"


def test_partial_row_outcome_counts_as_processed_but_blocks_its_group() -> None:
    partial = _source(2, "/partial.json")

    decision = decide_ingest(
        CHECKPOINT, (_group(2, _failure(partial, processed=True)),)
    )

    assert decision.processed_sources == (partial.path,)
    assert decision.workouts == 1
    assert decision.daily_points == 2
    assert decision.safe_watermark == CHECKPOINT
    assert decision.commit_required is True
    assert decision.status == "partial"


def test_all_failed_files_produce_failed_status_without_commit_or_checkpoint() -> None:
    failed = _source(2, "/failed.json")

    decision = decide_ingest(CHECKPOINT, (_group(2, _failure(failed)),))

    assert decision.processed_sources == ()
    assert decision.commit_required is False
    assert decision.success is False
    assert decision.status == "failed"
    assert decision.is_no_work is False


def test_transaction_fatal_failure_has_a_dedicated_empty_result_decision() -> None:
    failure = AppleHealthIngestFailure(stage="commit", reason="unavailable")

    decision = failed_ingest_decision(failure)

    assert decision.processed_sources == ()
    assert decision.failure_details == (failure,)
    assert decision.safe_watermark is None
    assert decision.checkpoint_to_save is None
    assert decision.commit_required is False
    assert decision.status == "failed"
    assert decision.alerts == (
        "Apple Health ingest failed; 1 failure(s) remain retryable. "
        "First failure: ingest run at commit (unavailable).",
    )
    assert decision.is_no_work is False


def test_failure_alert_and_reason_helpers_preserve_exact_safe_text_policy() -> None:
    failure = AppleHealthIngestFailure(
        stage="extract",
        reason="bad archive",
        file_path="/bad.zip",
    )

    assert failure_alert((failure,), partial=False) == (
        "Apple Health ingest failed; 1 failure(s) remain retryable. "
        "First failure: /bad.zip at extract (bad archive)."
    )
    assert safe_exception_reason(RuntimeError()) == "RuntimeError"
    assert safe_exception_reason(RuntimeError("  token=visible\n detail  ")) == (
        "token=visible detail"
    )
    assert len(safe_exception_reason(RuntimeError("x" * 300))) == 240
    assert normalise_failure_reason("  two\n words  ", fallback="parse") == "two words"
    assert normalise_failure_reason("   ", fallback="parse") == "parse"
    assert len(normalise_failure_reason("x" * 300, fallback="parse")) == 240


def test_outcome_facts_are_immutable() -> None:
    source = _source(2, "/immutable.json")
    outcome = _success(source)

    with pytest.raises(FrozenInstanceError):
        outcome.processed = False  # type: ignore[misc]
