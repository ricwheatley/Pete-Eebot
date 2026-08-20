from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pete_e.infrastructure.apple_health_ingestor import AppleHealthDropboxIngestor


UTC = timezone.utc
INITIAL_CHECKPOINT = datetime(2024, 1, 1, tzinfo=UTC)


def _valid_export(*, point_date: str, value: float = 1.0) -> bytes:
    return json.dumps(
        {
            "data": {
                "metrics": [
                    {
                        "name": "step_count",
                        "units": "count",
                        "data": [
                            {
                                "date": point_date,
                                "source": "Checkpoint Test Watch",
                                "qty": value,
                            }
                        ],
                    }
                ],
                "workouts": [],
            }
        }
    ).encode("utf-8")


@dataclass
class _Store:
    checkpoint: datetime = INITIAL_CHECKPOINT
    points: dict[tuple[str, str, datetime], float] = field(default_factory=dict)


class _Connection:
    def __init__(self, store: _Store) -> None:
        self.store = store
        self.commits = 0
        self.rollbacks = 0
        self.fail_commit = False
        self._snapshot: _Store | None = None

    def commit(self) -> None:
        if self.fail_commit:
            raise RuntimeError("simulated commit failure")
        self.commits += 1


class _ConnectionContext:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def __enter__(self) -> _Connection:
        self.connection._snapshot = copy.deepcopy(self.connection.store)
        return self.connection

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            snapshot = self.connection._snapshot
            assert snapshot is not None
            self.connection.store.checkpoint = snapshot.checkpoint
            self.connection.store.points = snapshot.points
            self.connection.rollbacks += 1


class _Dal:
    def __init__(self, store: _Store) -> None:
        self.connection_value = _Connection(store)

    def connection(self) -> _ConnectionContext:
        return _ConnectionContext(self.connection_value)


class _Client:
    health_metrics_path = "/metrics"
    workouts_path = "/workouts"

    def __init__(
        self,
        files: list[tuple[datetime, str]],
        contents: dict[str, bytes],
    ) -> None:
        self.files = files
        self.contents = contents
        self.download_failures: dict[str, int] = {}
        self.downloaded: list[str] = []

    def find_new_export_files(
        self,
        folder_path: str,
        since_datetime: datetime,
    ) -> list[tuple[datetime, str]]:
        if folder_path != self.health_metrics_path:
            return []
        return [(modified, path) for modified, path in self.files if modified > since_datetime]

    def download_as_bytes(self, dropbox_path: str) -> bytes:
        self.downloaded.append(dropbox_path)
        remaining_failures = self.download_failures.get(dropbox_path, 0)
        if remaining_failures:
            self.download_failures[dropbox_path] = remaining_failures - 1
            raise OSError("temporary Dropbox download failure")
        return self.contents[dropbox_path]


class _Writer:
    def __init__(self, conn: _Connection, factory: "_WriterFactory") -> None:
        self.conn = conn
        self.factory = factory

    def get_last_import_timestamp(self) -> datetime:
        return self.conn.store.checkpoint

    def upsert_all(self, parsed: dict) -> None:
        self.factory.upsert_calls += 1
        for point in parsed["daily_metric_points"]:
            key = (point.metric_name, point.device_name, point.date)
            self.conn.store.points[key] = point.value
        if self.factory.fail_write_on_call == self.factory.upsert_calls:
            raise RuntimeError("simulated database write failure")

    def save_last_import_timestamp(self, latest_file_timestamp: datetime) -> None:
        self.conn.store.checkpoint = latest_file_timestamp
        if self.factory.fail_checkpoint:
            raise RuntimeError("simulated checkpoint write failure")


class _WriterFactory:
    def __init__(self) -> None:
        self.upsert_calls = 0
        self.fail_write_on_call: int | None = None
        self.fail_checkpoint = False

    def __call__(self, conn: _Connection) -> _Writer:
        return _Writer(conn, self)


def _build_ingestor(
    files: list[tuple[datetime, str]],
    contents: dict[str, bytes],
    *,
    parser=None,
) -> tuple[AppleHealthDropboxIngestor, _Store, _Dal, _Client, _WriterFactory]:
    store = _Store()
    dal = _Dal(store)
    client = _Client(files, contents)
    writer_factory = _WriterFactory()
    ingestor = AppleHealthDropboxIngestor(
        dal=dal,  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
        parser=parser,
        writer_factory=writer_factory,  # type: ignore[arg-type]
    )
    return ingestor, store, dal, client, writer_factory


def test_malformed_first_valid_second_holds_checkpoint_and_retries_idempotently() -> None:
    malformed_time = datetime(2024, 1, 2, tzinfo=UTC)
    valid_time = datetime(2024, 1, 3, tzinfo=UTC)
    malformed_path = "/metrics/HealthAutoExport-malformed.json"
    valid_path = "/metrics/HealthAutoExport-valid.json"
    ingestor, store, dal, client, writer_factory = _build_ingestor(
        [(malformed_time, malformed_path), (valid_time, valid_path)],
        {
            malformed_path: b"{malformed",
            valid_path: _valid_export(point_date="2024-01-03 08:00:00 +0000"),
        },
    )

    first = ingestor.ingest()

    assert first.success is False
    assert first.statuses == {"Apple Health": "partial"}
    assert first.failures == ("Apple Health",)
    assert first.failure_details[0].file_path == malformed_path
    assert first.failure_details[0].stage == "extract"
    assert malformed_path in first.alerts[0]
    assert store.checkpoint == INITIAL_CHECKPOINT
    assert len(store.points) == 1
    assert dal.connection_value.commits == 1

    client.contents[malformed_path] = _valid_export(
        point_date="2024-01-02 08:00:00 +0000",
        value=2.0,
    )
    second = ingestor.ingest()

    assert second.success is True
    assert second.statuses == {"Apple Health": "ok"}
    assert second.failure_details == ()
    assert store.checkpoint == valid_time
    assert len(store.points) == 2
    assert writer_factory.upsert_calls == 3

    third = ingestor.ingest()

    assert third.success is True
    assert third.summary is not None
    assert third.summary.sources == []
    assert len(store.points) == 2


def test_valid_first_malformed_second_advances_only_to_valid_file() -> None:
    valid_time = datetime(2024, 1, 2, tzinfo=UTC)
    malformed_time = datetime(2024, 1, 3, tzinfo=UTC)
    valid_path = "/metrics/HealthAutoExport-valid.json"
    malformed_path = "/metrics/HealthAutoExport-malformed.json"
    ingestor, store, _, _, _ = _build_ingestor(
        [(valid_time, valid_path), (malformed_time, malformed_path)],
        {
            valid_path: _valid_export(point_date="2024-01-02 08:00:00 +0000"),
            malformed_path: b"not-json",
        },
    )

    result = ingestor.ingest()

    assert result.success is False
    assert result.statuses == {"Apple Health": "partial"}
    assert store.checkpoint == valid_time
    assert len(store.points) == 1


def test_all_malformed_is_failed_and_does_not_advance_checkpoint() -> None:
    first_path = "/metrics/HealthAutoExport-bad-1.json"
    second_path = "/metrics/HealthAutoExport-bad-2.json"
    ingestor, store, dal, _, _ = _build_ingestor(
        [
            (datetime(2024, 1, 2, tzinfo=UTC), first_path),
            (datetime(2024, 1, 3, tzinfo=UTC), second_path),
        ],
        {first_path: b"bad", second_path: b"also-bad"},
    )

    result = ingestor.ingest()

    assert result.success is False
    assert result.statuses == {"Apple Health": "failed"}
    assert len(result.failure_details) == 2
    assert len(result.alerts) == 1
    assert store.checkpoint == INITIAL_CHECKPOINT
    assert store.points == {}
    assert dal.connection_value.commits == 0


def test_transient_download_failure_succeeds_on_retry() -> None:
    modified = datetime(2024, 1, 2, tzinfo=UTC)
    path = "/metrics/HealthAutoExport-transient.json"
    ingestor, store, _, client, _ = _build_ingestor(
        [(modified, path)],
        {path: _valid_export(point_date="2024-01-02 08:00:00 +0000")},
    )
    client.download_failures[path] = 1

    first = ingestor.ingest()
    second = ingestor.ingest()

    assert first.success is False
    assert first.statuses == {"Apple Health": "failed"}
    assert first.failure_details[0].stage == "download"
    assert second.success is True
    assert store.checkpoint == modified
    assert len(store.points) == 1


def test_parser_exception_is_failed_and_retryable() -> None:
    class FailingParser:
        def parse(self, root):
            raise ValueError("parser rejected export structure")

    modified = datetime(2024, 1, 2, tzinfo=UTC)
    path = "/metrics/HealthAutoExport-parser.json"
    ingestor, store, dal, _, _ = _build_ingestor(
        [(modified, path)],
        {path: _valid_export(point_date="2024-01-02 08:00:00 +0000")},
        parser=FailingParser(),
    )

    result = ingestor.ingest()

    assert result.success is False
    assert result.statuses == {"Apple Health": "failed"}
    assert result.failure_details[0].stage == "parse"
    assert store.checkpoint == INITIAL_CHECKPOINT
    assert dal.connection_value.commits == 0


def test_parser_partial_rows_commit_valid_data_but_hold_checkpoint() -> None:
    modified = datetime(2024, 1, 2, tzinfo=UTC)
    path = "/metrics/HealthAutoExport-partial-rows.json"
    payload = json.loads(
        _valid_export(point_date="2024-01-02 08:00:00 +0000").decode("utf-8")
    )
    payload["data"]["metrics"][0]["data"].append(
        {
            "date": "2024-01-02 09:00:00 +0000",
            "source": "Checkpoint Test Watch",
            "qty": "not-a-number",
        }
    )
    ingestor, store, _, _, _ = _build_ingestor(
        [(modified, path)],
        {path: json.dumps(payload).encode("utf-8")},
    )

    result = ingestor.ingest()

    assert result.success is False
    assert result.statuses == {"Apple Health": "partial"}
    assert result.failure_details[0].stage == "parse"
    assert result.failure_details[0].reason == "parser skipped 1 invalid row(s)"
    assert store.checkpoint == INITIAL_CHECKPOINT
    assert len(store.points) == 1


def test_database_write_failure_rolls_back_data_and_checkpoint() -> None:
    modified = datetime(2024, 1, 2, tzinfo=UTC)
    path = "/metrics/HealthAutoExport-write.json"
    ingestor, store, dal, _, writer_factory = _build_ingestor(
        [(modified, path)],
        {path: _valid_export(point_date="2024-01-02 08:00:00 +0000")},
    )
    writer_factory.fail_write_on_call = 1

    result = ingestor.ingest()

    assert result.success is False
    assert result.statuses == {"Apple Health": "failed"}
    assert result.failure_details[0].stage == "write"
    assert result.failure_details[0].file_path == path
    assert store.points == {}
    assert store.checkpoint == INITIAL_CHECKPOINT
    assert dal.connection_value.rollbacks == 1


def test_checkpoint_write_failure_rolls_back_health_data() -> None:
    modified = datetime(2024, 1, 2, tzinfo=UTC)
    path = "/metrics/HealthAutoExport-checkpoint.json"
    ingestor, store, dal, _, writer_factory = _build_ingestor(
        [(modified, path)],
        {path: _valid_export(point_date="2024-01-02 08:00:00 +0000")},
    )
    writer_factory.fail_checkpoint = True

    result = ingestor.ingest()

    assert result.success is False
    assert result.statuses == {"Apple Health": "failed"}
    assert result.failure_details[0].stage == "checkpoint"
    assert store.points == {}
    assert store.checkpoint == INITIAL_CHECKPOINT
    assert dal.connection_value.rollbacks == 1
    assert dal.connection_value.commits == 0


def test_commit_failure_rolls_back_health_data_and_checkpoint() -> None:
    modified = datetime(2024, 1, 2, tzinfo=UTC)
    path = "/metrics/HealthAutoExport-commit.json"
    ingestor, store, dal, _, _ = _build_ingestor(
        [(modified, path)],
        {path: _valid_export(point_date="2024-01-02 08:00:00 +0000")},
    )
    dal.connection_value.fail_commit = True

    result = ingestor.ingest()

    assert result.success is False
    assert result.statuses == {"Apple Health": "failed"}
    assert result.failure_details[0].stage == "commit"
    assert store.points == {}
    assert store.checkpoint == INITIAL_CHECKPOINT
    assert dal.connection_value.rollbacks == 1


def test_equal_timestamp_group_is_replayed_if_any_peer_fails() -> None:
    modified = datetime(2024, 1, 2, tzinfo=UTC)
    valid_path = "/metrics/HealthAutoExport-a-valid.json"
    malformed_path = "/metrics/HealthAutoExport-z-malformed.json"
    ingestor, store, _, client, _ = _build_ingestor(
        [(modified, malformed_path), (modified, valid_path)],
        {
            valid_path: _valid_export(point_date="2024-01-02 08:00:00 +0000"),
            malformed_path: b"bad-json",
        },
    )

    first = ingestor.ingest()

    assert first.success is False
    assert first.statuses == {"Apple Health": "partial"}
    assert client.downloaded[:2] == [valid_path, malformed_path]
    assert store.checkpoint == INITIAL_CHECKPOINT
    assert len(store.points) == 1

    client.contents[malformed_path] = _valid_export(
        point_date="2024-01-02 09:00:00 +0000",
        value=2.0,
    )
    second = ingestor.ingest()

    assert second.success is True
    assert store.checkpoint == modified
    assert len(store.points) == 2
