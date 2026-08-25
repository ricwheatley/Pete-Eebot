from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from pete_e.infrastructure import apple_health_ingestor, log_utils
from pete_e.infrastructure.apple_health_ingestor import AppleHealthDropboxIngestor


UTC = timezone.utc
INITIAL_CHECKPOINT = datetime(2024, 1, 1, tzinfo=UTC)


def _payload(name: str) -> bytes:
    return json.dumps(
        {
            "data": {
                "metrics": [{"name": name, "units": "count", "data": []}],
                "workouts": [],
            }
        }
    ).encode()


def _parsed(name: str, *, skipped: int = 0) -> dict[str, Any]:
    return {
        "_name": name,
        "daily_metric_points": [object()],
        "hr_summaries": [],
        "sleep_summaries": [],
        "workout_headers": [object()],
        "workout_hr": [],
        "workout_steps": [],
        "workout_energy": [],
        "workout_hr_recovery": [],
        "skipped_row_count": skipped,
    }


@dataclass
class _Store:
    checkpoint: datetime | None = INITIAL_CHECKPOINT
    writes: list[str] = field(default_factory=list)


class _Connection:
    def __init__(self, scenario: "_Scenario") -> None:
        self.scenario = scenario
        self._snapshot: _Store | None = None

    def commit(self) -> None:
        self.scenario.events.append("commit")
        if self.scenario.commit_error is not None:
            raise self.scenario.commit_error


class _ConnectionContext:
    def __init__(self, scenario: "_Scenario") -> None:
        self.scenario = scenario
        self.connection = _Connection(scenario)

    def __enter__(self) -> _Connection:
        self.scenario.events.append("connection.enter")
        if self.scenario.enter_error is not None:
            raise self.scenario.enter_error
        self.connection._snapshot = copy.deepcopy(self.scenario.store)
        return self.connection

    def __exit__(self, exc_type, exc, traceback) -> None:
        name = "none" if exc_type is None else exc_type.__name__
        self.scenario.events.append(f"connection.exit:{name}")
        if exc_type is not None:
            snapshot = self.connection._snapshot
            assert snapshot is not None
            self.scenario.store.checkpoint = snapshot.checkpoint
            self.scenario.store.writes = snapshot.writes
            self.scenario.events.append("rollback")


class _Dal:
    def __init__(self, scenario: "_Scenario") -> None:
        self.scenario = scenario

    def connection(self) -> _ConnectionContext:
        self.scenario.events.append("dal.connection")
        if self.scenario.connection_error is not None:
            raise self.scenario.connection_error
        return _ConnectionContext(self.scenario)


class _Client:
    health_metrics_path = "/metrics"
    workouts_path = "/workouts"

    def __init__(self, scenario: "_Scenario") -> None:
        self.scenario = scenario

    def find_new_export_files(
        self,
        folder_path: str,
        since_datetime: datetime,
    ) -> list[tuple[datetime, str]]:
        self.scenario.events.append(
            f"discover:{folder_path}:{since_datetime.isoformat()}"
        )
        if self.scenario.discovery_error is not None:
            raise self.scenario.discovery_error
        return [
            item
            for item in self.scenario.listings.get(folder_path, [])
            if _normalised(item[0]) > since_datetime
        ]

    def download_as_bytes(self, dropbox_path: str) -> bytes:
        self.scenario.events.append(f"download:{dropbox_path}")
        outcome = self.scenario.downloads[dropbox_path]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _Parser:
    def __init__(self, scenario: "_Scenario") -> None:
        self.scenario = scenario

    def parse(self, root: object) -> dict[str, Any]:
        assert isinstance(root, dict)
        metrics = root["data"]["metrics"]
        name = metrics[0]["name"]
        self.scenario.events.append(f"parse:{name}")
        outcome = self.scenario.parse_outcomes.get(name, _parsed(name))
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _Writer:
    def __init__(self, connection: _Connection, scenario: "_Scenario") -> None:
        self.connection = connection
        self.scenario = scenario

    def get_last_import_timestamp(self) -> datetime | None:
        self.scenario.events.append("checkpoint.read")
        if self.scenario.checkpoint_read_error is not None:
            raise self.scenario.checkpoint_read_error
        return self.scenario.store.checkpoint

    def upsert_all(self, parsed: dict[str, Any]) -> None:
        name = parsed["_name"]
        self.scenario.events.append(f"write:{name}")
        self.scenario.store.writes.append(name)
        if self.scenario.write_error_for == name:
            raise RuntimeError("  database\nwrite secret  ")

    def save_last_import_timestamp(self, latest_file_timestamp: datetime) -> None:
        self.scenario.events.append(
            f"checkpoint.save:{latest_file_timestamp.isoformat()}"
        )
        self.scenario.store.checkpoint = latest_file_timestamp
        if self.scenario.checkpoint_write_error is not None:
            raise self.scenario.checkpoint_write_error


class _WriterFactory:
    def __init__(self, scenario: "_Scenario") -> None:
        self.scenario = scenario

    def __call__(self, connection: _Connection) -> _Writer:
        self.scenario.events.append("writer.create")
        if self.scenario.writer_error is not None:
            raise self.scenario.writer_error
        return _Writer(connection, self.scenario)


@dataclass
class _Scenario:
    store: _Store = field(default_factory=_Store)
    events: list[str] = field(default_factory=list)
    listings: dict[str, list[tuple[datetime, str]]] = field(default_factory=dict)
    downloads: dict[str, bytes | BaseException] = field(default_factory=dict)
    parse_outcomes: dict[str, dict[str, Any] | BaseException] = field(
        default_factory=dict
    )
    connection_error: BaseException | None = None
    enter_error: BaseException | None = None
    writer_error: BaseException | None = None
    checkpoint_read_error: BaseException | None = None
    discovery_error: BaseException | None = None
    write_error_for: str | None = None
    checkpoint_write_error: BaseException | None = None
    commit_error: BaseException | None = None


def _normalised(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def _ingestor(scenario: _Scenario) -> AppleHealthDropboxIngestor:
    return AppleHealthDropboxIngestor(
        dal=_Dal(scenario),  # type: ignore[arg-type]
        client=_Client(scenario),  # type: ignore[arg-type]
        parser=_Parser(scenario),  # type: ignore[arg-type]
        writer_factory=_WriterFactory(scenario),  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("checkpoint", "expected_since"),
    [
        (None, datetime(1970, 1, 1, tzinfo=UTC)),
        (datetime(2024, 1, 2), datetime(2024, 1, 2, tzinfo=UTC)),
    ],
)
def test_no_work_preserves_initialisation_discovery_and_transaction_order(
    checkpoint: datetime | None,
    expected_since: datetime,
) -> None:
    scenario = _Scenario(
        store=_Store(checkpoint=checkpoint),
        listings={
            "/metrics": [
                (expected_since - timedelta(seconds=1), "/older.json"),
                (expected_since, "/equal.json"),
            ],
            "/workouts": [],
        },
    )

    result = _ingestor(scenario).ingest()

    assert result.success is True
    assert result.summary is not None
    assert result.summary.sources == []
    assert result.statuses == {"Apple Health": "ok"}
    assert result.alerts == ()
    assert scenario.events == [
        "dal.connection",
        "connection.enter",
        "writer.create",
        "checkpoint.read",
        f"discover:/metrics:{expected_since.isoformat()}",
        f"discover:/workouts:{expected_since.isoformat()}",
        "connection.exit:none",
    ]


def test_two_listing_results_are_normalised_then_ordered_by_timestamp_and_path() -> (
    None
):
    ten_utc = datetime(2024, 1, 2, 10, tzinfo=UTC)
    noon_naive = datetime(2024, 1, 2, 12)
    scenario = _Scenario(
        listings={
            "/metrics": [
                (noon_naive, "/z.json"),
                (ten_utc, "/b.json"),
                (INITIAL_CHECKPOINT, "/equal-checkpoint.json"),
            ],
            "/workouts": [
                (datetime(2024, 1, 2, 12, tzinfo=UTC), "/a.json"),
                (
                    datetime(2024, 1, 2, 11, tzinfo=timezone(timedelta(hours=1))),
                    "/c.json",
                ),
                (datetime(2024, 1, 2, 12, tzinfo=UTC), "/A.json"),
            ],
        },
        downloads={
            path: _payload(path)
            for path in ("/z.json", "/b.json", "/a.json", "/c.json", "/A.json")
        },
    )

    result = _ingestor(scenario).ingest()

    assert result.summary is not None
    assert result.summary.sources == (
        "/b.json",
        "/c.json",
        "/A.json",
        "/a.json",
        "/z.json",
    )
    assert result.summary.workouts == 5
    assert result.summary.daily_points == 5
    assert scenario.store.checkpoint == noon_naive.replace(tzinfo=UTC)
    assert [event for event in scenario.events if event.startswith("download:")] == [
        "download:/b.json",
        "download:/c.json",
        "download:/A.json",
        "download:/a.json",
        "download:/z.json",
    ]
    assert scenario.events[-3:] == [
        "checkpoint.save:2024-01-02T12:00:00+00:00",
        "commit",
        "connection.exit:none",
    ]


@pytest.mark.parametrize(
    ("path", "download", "parse_outcome", "expected_stage", "expected_reason"),
    [
        (
            "/download.json",
            OSError("  temporary\nDropbox failure  "),
            None,
            "download",
            "temporary Dropbox failure",
        ),
        ("/invalid.json", b"not-json", None, "extract", "no extractable JSON object"),
        ("/array.json", b"[]", None, "extract", "no extractable JSON object"),
        (
            "/data-array.json",
            b'{"data": []}',
            None,
            "extract",
            "JSON data field is not an object",
        ),
        (
            "/parse.json",
            _payload("parse"),
            ValueError(),
            "parse",
            "ValueError",
        ),
    ],
)
def test_recoverable_file_failures_return_safe_retryable_details_without_commit(
    path: str,
    download: bytes | BaseException,
    parse_outcome: BaseException | None,
    expected_stage: str,
    expected_reason: str,
) -> None:
    modified = datetime(2024, 1, 2, tzinfo=UTC)
    scenario = _Scenario(
        listings={"/metrics": [(modified, path)], "/workouts": []},
        downloads={path: download},
        parse_outcomes={"parse": parse_outcome} if parse_outcome is not None else {},
    )

    result = _ingestor(scenario).ingest()

    assert result.success is False
    assert result.summary is not None
    assert result.summary.sources == ()
    assert result.statuses == {"Apple Health": "failed"}
    assert result.failures == ("Apple Health",)
    assert len(result.failure_details) == 1
    assert result.failure_details[0].stage == expected_stage
    assert result.failure_details[0].reason == expected_reason
    assert result.failure_details[0].file_path == path
    assert result.failure_details[0].modified_at == modified
    assert expected_reason in result.alerts[0]
    assert "commit" not in scenario.events
    assert not any(event.startswith("checkpoint.save:") for event in scenario.events)
    assert scenario.events[-1] == "connection.exit:none"


def test_partial_rows_and_later_success_commit_but_unsafe_group_blocks_checkpoint() -> (
    None
):
    first = datetime(2024, 1, 2, tzinfo=UTC)
    later = datetime(2024, 1, 3, tzinfo=UTC)
    partial_path = "/a-partial.json"
    failed_peer_path = "/b-download.json"
    later_path = "/later.json"
    scenario = _Scenario(
        listings={
            "/metrics": [
                (later, later_path),
                (first, failed_peer_path),
                (first, partial_path),
            ],
            "/workouts": [],
        },
        downloads={
            partial_path: _payload("partial"),
            failed_peer_path: OSError("peer unavailable"),
            later_path: _payload("later"),
        },
        parse_outcomes={"partial": _parsed("partial", skipped=2)},
    )

    result = _ingestor(scenario).ingest()

    assert result.success is False
    assert result.summary is not None
    assert result.summary.sources == (partial_path, later_path)
    assert result.summary.workouts == 2
    assert result.summary.daily_points == 2
    assert result.statuses == {"Apple Health": "partial"}
    assert [failure.stage for failure in result.failure_details] == [
        "parse",
        "download",
    ]
    assert result.failure_details[0].reason == "parser skipped 2 invalid row(s)"
    assert scenario.store.checkpoint == INITIAL_CHECKPOINT
    assert scenario.store.writes == ["partial", "later"]
    assert "commit" in scenario.events
    assert not any(event.startswith("checkpoint.save:") for event in scenario.events)
    assert result.alerts == (
        "Apple Health ingest partially completed; 2 failure(s) remain retryable. "
        "First failure: /a-partial.json at parse (parser skipped 2 invalid row(s)).",
    )


@pytest.mark.parametrize(
    ("failure_kind", "expected_stage", "expected_prefix"),
    [
        ("write", "write", ["write:write"]),
        (
            "checkpoint",
            "checkpoint",
            ["write:checkpoint", "checkpoint.save:2024-01-02T00:00:00+00:00"],
        ),
        (
            "commit",
            "commit",
            [
                "write:commit",
                "checkpoint.save:2024-01-02T00:00:00+00:00",
                "commit",
            ],
        ),
    ],
)
def test_transaction_fatal_failures_roll_back_and_return_empty_failed_result(
    failure_kind: str,
    expected_stage: str,
    expected_prefix: list[str],
) -> None:
    modified = datetime(2024, 1, 2, tzinfo=UTC)
    path = f"/{failure_kind}.json"
    scenario = _Scenario(
        listings={"/metrics": [(modified, path)], "/workouts": []},
        downloads={path: _payload(failure_kind)},
        write_error_for=failure_kind if failure_kind == "write" else None,
        checkpoint_write_error=RuntimeError("checkpoint unavailable")
        if failure_kind == "checkpoint"
        else None,
        commit_error=RuntimeError("commit unavailable")
        if failure_kind == "commit"
        else None,
    )

    result = _ingestor(scenario).ingest()

    assert result.success is False
    assert result.summary is not None
    assert result.summary.sources == ()
    assert result.summary.workouts == 0
    assert result.summary.daily_points == 0
    assert result.statuses == {"Apple Health": "failed"}
    assert result.failure_details[0].stage == expected_stage
    assert scenario.store.writes == []
    assert scenario.store.checkpoint == INITIAL_CHECKPOINT
    assert scenario.events[-2:] == ["connection.exit:AppleIngestError", "rollback"]
    indices = [scenario.events.index(event) for event in expected_prefix]
    assert indices == sorted(indices)


@pytest.mark.parametrize(
    ("field", "expected_stage"),
    [
        ("connection_error", "connection"),
        ("writer_error", "initialise_writer"),
        ("checkpoint_read_error", "checkpoint"),
        ("discovery_error", "discover_exports"),
    ],
)
def test_run_level_failure_stage_mapping_is_stable(
    field: str, expected_stage: str
) -> None:
    scenario = _Scenario()
    setattr(scenario, field, RuntimeError(f"{field} unavailable"))

    result = _ingestor(scenario).ingest()

    assert result.success is False
    assert result.statuses == {"Apple Health": "failed"}
    assert result.failure_details[0].stage == expected_stage
    assert result.failure_details[0].file_path is None


def test_connection_enter_failure_remains_an_unexpected_failure() -> None:
    scenario = _Scenario(enter_error=RuntimeError("context enter unavailable"))

    result = _ingestor(scenario).ingest()

    assert result.failure_details[0].stage == "unexpected"
    assert result.failure_details[0].reason == "context enter unavailable"


@pytest.mark.parametrize(
    ("checkpoint", "expected"),
    [
        (None, None),
        (datetime(2024, 1, 2), datetime(2024, 1, 2, tzinfo=UTC)),
        (
            datetime(2024, 1, 2, 12, tzinfo=timezone(timedelta(hours=1))),
            datetime(2024, 1, 2, 11, tzinfo=UTC),
        ),
    ],
)
def test_public_checkpoint_read_preserves_none_and_normalises_timestamps(
    checkpoint: datetime | None,
    expected: datetime | None,
) -> None:
    scenario = _Scenario(store=_Store(checkpoint=checkpoint))

    result = _ingestor(scenario).get_last_import_timestamp()

    assert result == expected
    assert scenario.events == [
        "dal.connection",
        "connection.enter",
        "writer.create",
        "checkpoint.read",
        "connection.exit:none",
    ]


def test_public_checkpoint_read_converts_connection_failure_to_checkpoint_error() -> (
    None
):
    scenario = _Scenario(
        connection_error=RuntimeError("checkpoint connection unavailable")
    )

    with pytest.raises(apple_health_ingestor.AppleIngestError) as captured:
        _ingestor(scenario).get_last_import_timestamp()

    assert captured.value.stage == "checkpoint"
    assert captured.value.reason == "checkpoint connection unavailable"


def test_extraction_boundary_exception_is_normalised_and_logged_before_next_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modified = datetime(2024, 1, 2, tzinfo=UTC)
    first_path = "/a.json"
    second_path = "/b.json"
    scenario = _Scenario(
        listings={
            "/metrics": [(modified, second_path), (modified, first_path)],
            "/workouts": [],
        },
        downloads={first_path: b"first", second_path: _payload("second")},
    )
    real_extract = apple_health_ingestor._get_json_from_content

    def _extract(path: str, content: bytes) -> dict[str, Any] | None:
        if path == first_path:
            raise RuntimeError("  secret\n extraction detail  ")
        return real_extract(path, content)

    monkeypatch.setattr(apple_health_ingestor, "_get_json_from_content", _extract)
    monkeypatch.setattr(
        log_utils,
        "error",
        lambda message: scenario.events.append(f"error:{message}"),
    )

    result = _ingestor(scenario).ingest()

    assert result.failure_details[0].reason == "secret extraction detail"
    failure_log = (
        "error:Apple Health ingest failure at extract for /a.json: "
        "secret extraction detail"
    )
    assert scenario.events.index(failure_log) < scenario.events.index(
        "download:/b.json"
    )


def test_safe_reason_preserves_current_whitespace_fallback_truncation_and_content() -> (
    None
):
    assert AppleHealthDropboxIngestor._safe_reason(RuntimeError()) == "RuntimeError"
    assert (
        AppleHealthDropboxIngestor._safe_reason(RuntimeError(" api\n token=visible "))
        == "api token=visible"
    )
    assert len(AppleHealthDropboxIngestor._safe_reason(RuntimeError("x" * 300))) == 240
