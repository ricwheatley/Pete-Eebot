import io
import json
import zipfile
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import List

import pytest

from pete_e.application import apple_dropbox_ingest
from pete_e.domain.daily_sync import AppleHealthImportSummary, AppleHealthIngestResult
from pete_e.infrastructure.apple_health_ingestor import (
    AppleHealthDropboxIngestor,
    AppleIngestError,
    _get_json_from_content,
)


def _build_dummy_writer(writer_calls: List[SimpleNamespace]):
    class DummyWriter:
        def __init__(self, conn) -> None:
            self.conn = conn

        def get_last_import_timestamp(self):
            return datetime(2024, 1, 1, tzinfo=timezone.utc)

        def upsert_all(self, parsed):
            writer_calls.append(SimpleNamespace(action="upsert", payload=parsed))

        def save_last_import_timestamp(self, latest_file_timestamp):
            writer_calls.append(SimpleNamespace(action="checkpoint", payload=latest_file_timestamp))

    return DummyWriter


def test_get_json_from_content_supports_zip_files():
    payload = {"data": {"metrics": [{"name": "steps"}]}}
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("Health.json", json.dumps(payload))
        zipped_bytes = buffer.getvalue()

    extracted = _get_json_from_content("HealthAutoExport.zip", zipped_bytes)

    assert extracted == payload


def test_ingestor_processes_new_files():
    class DummyConn:
        def __init__(self) -> None:
            self.committed = False

        def commit(self) -> None:
            self.committed = True

    class DummyConnCtx:
        def __init__(self) -> None:
            self.conn = DummyConn()

        def __enter__(self) -> DummyConn:
            return self.conn

        def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - contextmanager API
            pass

    class DummyClient:
        def __init__(self) -> None:
            self.health_metrics_path = "/metrics"
            self.workouts_path = "/workouts"
            self.downloaded: List[str] = []

        def find_new_export_files(self, folder_path, since_datetime):
            if folder_path == self.health_metrics_path:
                return [(datetime(2024, 1, 2, tzinfo=timezone.utc), "metrics.json")]
            return [(datetime(2024, 1, 3, tzinfo=timezone.utc), "workouts.zip")]

        def download_as_bytes(self, dropbox_path: str) -> bytes:
            self.downloaded.append(dropbox_path)
            if dropbox_path.endswith(".json"):
                return json.dumps({"data": {"metrics": [], "workouts": []}}).encode("utf-8")

            with io.BytesIO() as buffer:
                with zipfile.ZipFile(buffer, "w") as archive:
                    archive.writestr(
                        "payload.json",
                        json.dumps({"data": {"metrics": [], "workouts": []}}),
                    )
                return buffer.getvalue()

    class DummyParser:
        def __init__(self) -> None:
            self.calls = 0

        def parse(self, root):
            self.calls += 1
            metric_point = SimpleNamespace(
                device_name="Watch",
                metric_name="steps",
                unit="count",
                value=1.0,
                date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )

            return {
                "daily_metric_points": [metric_point],
                "hr_summaries": [],
                "sleep_summaries": [],
                "workout_headers": [],
                "workout_hr": [],
                "workout_steps": [],
                "workout_energy": [],
                "workout_hr_recovery": [],
            }

    class DummyDal:
        def __init__(self) -> None:
            self.ctx = DummyConnCtx()

        def connection(self):
            return self.ctx

    dummy_client = DummyClient()
    dummy_parser = DummyParser()
    writer_calls: List[SimpleNamespace] = []

    ingestor = AppleHealthDropboxIngestor(
        dal=DummyDal(),
        client=dummy_client, 
        parser=dummy_parser,
        writer_factory=_build_dummy_writer(writer_calls),
    )

    result = ingestor.ingest()

    assert result.success is True
    assert isinstance(result.summary, AppleHealthImportSummary)
    assert list(result.summary.sources) == ["metrics.json", "workouts.zip"]
    assert result.summary.daily_points == 2
    assert result.summary.workouts == 0
    assert dummy_parser.calls == 2
    assert writer_calls[0].action == "upsert"
    assert writer_calls[-1].action == "checkpoint"
    assert dummy_client.downloaded == ["metrics.json", "workouts.zip"]


def test_ingestor_skips_already_processed_files():
    class DummyConn:
        def __init__(self) -> None:
            self.committed = False

        def commit(self) -> None:
            self.committed = True

    class DummyConnCtx:
        def __init__(self) -> None:
            self.conn = DummyConn()

        def __enter__(self):
            return self.conn

        def __exit__(self, exc_type, exc, tb):  # pragma: no cover - contextmanager API
            pass

    class DummyClient:
        health_metrics_path = "/metrics"
        workouts_path = "/workouts"

        def find_new_export_files(self, folder_path, since_datetime):
            return []

        def download_as_bytes(self, dropbox_path: str) -> bytes:  # pragma: no cover - unused
            raise AssertionError("download should not be called")

    class DummyParser:
        def parse(self, root):  # pragma: no cover - unused
            raise AssertionError("parser should not be invoked when no files found")

    class DummyWriter:
        def __init__(self, conn) -> None:
            self.conn = conn

        def get_last_import_timestamp(self):
            return datetime(2024, 1, 5, tzinfo=timezone.utc)

        def upsert_all(self, parsed):  # pragma: no cover - unused
            raise AssertionError

        def save_last_import_timestamp(self, latest_file_timestamp):  # pragma: no cover - unused
            raise AssertionError

    class DummyDal:
        def __init__(self) -> None:
            self.ctx = DummyConnCtx()

        def connection(self):
            return self.ctx

    ingestor = AppleHealthDropboxIngestor(
        dal=DummyDal(),
        client=DummyClient(),
        parser=DummyParser(),
        writer_factory=DummyWriter,
    )

    result = ingestor.ingest()

    assert result.success is True
    assert result.summary == AppleHealthImportSummary(
        sources=[], workouts=0, daily_points=0, hr_days=0, sleep_days=0
    )


def test_ingestor_raises_on_parser_failure():
    class DummyConn:
        def commit(self):  # pragma: no cover - not reached
            raise AssertionError("commit should not be called on failure")

    class DummyConnCtx:
        def __enter__(self):
            return DummyConn()

        def __exit__(self, exc_type, exc, tb):  # pragma: no cover - contextmanager API
            pass

    class DummyClient:
        def __init__(self) -> None:
            self.health_metrics_path = "/metrics"
            self.workouts_path = "/workouts"

        def find_new_export_files(self, folder_path, since_datetime):
            if folder_path == self.health_metrics_path:
                return [(datetime(2024, 1, 2, tzinfo=timezone.utc), "bad.json")]
            return []

        def download_as_bytes(self, dropbox_path: str) -> bytes:
            return json.dumps({"data": {"metrics": [], "workouts": []}}).encode("utf-8")

    class DummyParser:
        def parse(self, root):
            raise ValueError("corrupt payload")

    class DummyWriter:
        def __init__(self, conn) -> None:
            self.conn = conn

        def get_last_import_timestamp(self):
            return datetime(2024, 1, 1, tzinfo=timezone.utc)

        def upsert_all(self, parsed):  # pragma: no cover - not reached
            raise AssertionError

        def save_last_import_timestamp(self, latest_file_timestamp):  # pragma: no cover - not reached
            raise AssertionError

    class DummyDal:
        def __init__(self) -> None:
            self.ctx = DummyConnCtx()

        def connection(self):
            return self.ctx

    ingestor = AppleHealthDropboxIngestor(
        dal=DummyDal(),
        client=DummyClient(),
        parser=DummyParser(),
        writer_factory=DummyWriter,
    )

    with pytest.raises(AppleIngestError) as excinfo:
        ingestor.ingest()

    assert excinfo.value.stage == "parse"
    assert excinfo.value.file_path == "bad.json"


def test_application_wrapper_uses_injected_ingestor():
    class DummyIngestor:
        def __init__(self) -> None:
            self.calls = 0

        def ingest(self):
            self.calls += 1
            return AppleHealthIngestResult(
                success=True,
                summary=AppleHealthImportSummary(
                    sources=("foo",), workouts=0, daily_points=0, hr_days=0, sleep_days=0
                ),
                failures=(),
                statuses={"Apple Health": "ok"},
                alerts=(),
            )

        def get_last_import_timestamp(self):
            return datetime(2024, 1, 1, tzinfo=timezone.utc)

    dummy_ingestor = DummyIngestor()

    result = apple_dropbox_ingest.run_apple_health_ingest(ingestor=dummy_ingestor)
    assert result.success is True
    assert dummy_ingestor.calls == 1

    timestamp = apple_dropbox_ingest.get_last_successful_import_timestamp(ingestor=dummy_ingestor)
    assert timestamp == datetime(2024, 1, 1, tzinfo=timezone.utc)

