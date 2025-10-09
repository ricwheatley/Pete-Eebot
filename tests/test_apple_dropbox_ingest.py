import io
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import List
import zipfile

import pytest

from pete_e.application import apple_dropbox_ingest


def test_get_json_from_content_supports_zip_files():
    payload = {"data": {"metrics": [{"name": "steps"}]}}
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("Health.json", json.dumps(payload))
        zipped_bytes = buffer.getvalue()

    extracted = apple_dropbox_ingest._get_json_from_content("HealthAutoExport.zip", zipped_bytes)

    assert extracted == payload


def test_run_apple_health_ingest_processes_new_files(monkeypatch):
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
            # Return a minimal structure expected by the writer.
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

    class DummyWriter:
        def __init__(self, conn) -> None:
            self.conn = conn
            self.upserts: List[dict] = []
            self.checkpoints: List[datetime] = []

        def get_last_import_timestamp(self):
            return datetime(2024, 1, 1, tzinfo=timezone.utc)

        def upsert_all(self, parsed):
            self.upserts.append(parsed)

        def save_last_import_timestamp(self, latest_file_timestamp: datetime) -> None:
            self.checkpoints.append(latest_file_timestamp)

    dummy_client = DummyClient()
    dummy_parser = DummyParser()
    writer_instances: List[DummyWriter] = []

    monkeypatch.setattr(apple_dropbox_ingest, "AppleDropboxClient", lambda: dummy_client)
    monkeypatch.setattr(apple_dropbox_ingest, "AppleHealthParser", lambda: dummy_parser)

    def _writer_factory(conn):
        writer = DummyWriter(conn)
        writer_instances.append(writer)
        return writer

    class DummyDal:
        def __init__(self) -> None:
            self.ctx = DummyConnCtx()
            self.closed = False

        def connection(self):
            return self.ctx

        def close(self) -> None:
            self.closed = True

    dummy_dal = DummyDal()

    monkeypatch.setattr(apple_dropbox_ingest, "AppleHealthWriter", _writer_factory)
    monkeypatch.setattr(apple_dropbox_ingest, "_get_dal", lambda: dummy_dal)

    report = apple_dropbox_ingest.run_apple_health_ingest()

    assert report.sources == ["metrics.json", "workouts.zip"]
    assert report.daily_points == 2  # two files processed
    assert report.workouts == 0

    assert dummy_parser.calls == 2
    assert len(writer_instances) == 1
    writer = writer_instances[0]
    assert len(writer.upserts) == 2
    assert writer.checkpoints == [datetime(2024, 1, 3, tzinfo=timezone.utc)]
    assert writer.conn.committed
    assert dummy_dal.closed


def test_run_apple_health_ingest_skips_already_processed_files(monkeypatch):
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
            # All files are older than the recorded checkpoint, so they are skipped.
            return []

        def download_as_bytes(self, dropbox_path: str) -> bytes:  # pragma: no cover - unused
            raise AssertionError("download should not be called")

    class DummyParser:
        def parse(self, root):  # pragma: no cover - unused
            raise AssertionError("parser should not be invoked when no files found")

    class DummyWriter:
        def __init__(self, conn) -> None:
            self.conn = conn
            self.checkpoints = []

        def get_last_import_timestamp(self):
            from datetime import datetime, timezone

            return datetime(2024, 1, 5, tzinfo=timezone.utc)

        def upsert_all(self, parsed):  # pragma: no cover - unused
            raise AssertionError("upsert should not be invoked when no files found")

        def save_last_import_timestamp(self, latest_file_timestamp):
            self.checkpoints.append(latest_file_timestamp)

    class DummyDal:
        def __init__(self) -> None:
            self.ctx = DummyConnCtx()
            self.closed = False

        def connection(self):
            return self.ctx

        def close(self) -> None:
            self.closed = True

    dummy_dal = DummyDal()

    monkeypatch.setattr(apple_dropbox_ingest, "AppleDropboxClient", lambda: DummyClient())
    monkeypatch.setattr(apple_dropbox_ingest, "AppleHealthParser", lambda: DummyParser())
    monkeypatch.setattr(apple_dropbox_ingest, "AppleHealthWriter", lambda conn: DummyWriter(conn))
    monkeypatch.setattr(apple_dropbox_ingest, "_get_dal", lambda: dummy_dal)

    report = apple_dropbox_ingest.run_apple_health_ingest()

    assert report.sources == []
    assert report.daily_points == 0
    assert report.workouts == 0
    assert dummy_dal.closed


def test_run_apple_health_ingest_raises_on_parser_failure(monkeypatch):
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
            from datetime import datetime, timezone

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
            from datetime import datetime, timezone

            return datetime(2024, 1, 1, tzinfo=timezone.utc)

        def upsert_all(self, parsed):  # pragma: no cover - not reached
            raise AssertionError

        def save_last_import_timestamp(self, latest_file_timestamp):  # pragma: no cover - not reached
            raise AssertionError

    class DummyDal:
        def __init__(self) -> None:
            self.ctx = DummyConnCtx()
            self.closed = False

        def connection(self):
            return self.ctx

        def close(self) -> None:
            self.closed = True

    dummy_dal = DummyDal()

    monkeypatch.setattr(apple_dropbox_ingest, "AppleDropboxClient", lambda: DummyClient())
    monkeypatch.setattr(apple_dropbox_ingest, "AppleHealthParser", lambda: DummyParser())
    monkeypatch.setattr(apple_dropbox_ingest, "AppleHealthWriter", lambda conn: DummyWriter(conn))
    monkeypatch.setattr(apple_dropbox_ingest, "_get_dal", lambda: dummy_dal)

    with pytest.raises(apple_dropbox_ingest.AppleIngestError) as excinfo:
        apple_dropbox_ingest.run_apple_health_ingest()

    assert excinfo.value.stage == "parse"
    assert excinfo.value.file_path == "bad.json"
    assert dummy_dal.closed
