"""Infrastructure implementation for importing Apple Health data."""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional

from pete_e.domain.daily_sync import (
    AppleHealthImportSummary,
    AppleHealthIngestResult,
    AppleHealthIngestor,
)
from pete_e.infrastructure import log_utils
from pete_e.infrastructure.apple_dropbox_client import AppleDropboxClient
from pete_e.infrastructure.apple_parser import AppleHealthParser
from pete_e.infrastructure.apple_writer import AppleHealthWriter
from pete_e.infrastructure.postgres_dal import PostgresDal


@dataclass(eq=False)
class AppleIngestError(Exception):
    """Raised when the Apple Dropbox ingest encounters a recoverable failure."""

    stage: str
    reason: str
    file_path: Optional[str] = None

    def __post_init__(self) -> None:  # pragma: no cover - simple data plumbing
        super().__init__(self._compose_message())

    def _compose_message(self) -> str:
        parts = [self.stage, self.reason]
        message = " - ".join(part for part in parts if part)
        if self.file_path:
            message = f"{message} [{self.file_path}]"
        return message

    def __str__(self) -> str:  # pragma: no cover - defers to _compose_message
        return self._compose_message()


def _get_json_from_content(path: str, content_bytes: bytes) -> Optional[Dict]:
    """Extract JSON data from either a raw file or a zip archive."""

    try:
        if path.lower().endswith(".zip"):
            log_utils.info(f"Extracting JSON from zip file: {path}")
            with io.BytesIO(content_bytes) as bio:
                with zipfile.ZipFile(bio, "r") as zf:
                    json_files = [f for f in zf.namelist() if f.endswith(".json")]
                    if not json_files:
                        log_utils.warn(f"No JSON file found in the zip archive: {path}")
                        return None
                    with zf.open(json_files[0]) as json_file:
                        return json.load(json_file)
        elif path.lower().endswith(".json"):
            log_utils.info(f"Parsing raw JSON file: {path}")
            return json.loads(content_bytes)
        else:
            log_utils.warn(
                f"Unsupported file type encountered: {path}. Only .zip and .json are supported."
            )
            return None
    except (zipfile.BadZipFile, json.JSONDecodeError) as exc:
        log_utils.error(f"Failed to extract or parse JSON from file {path}: {exc}")
        return None


class AppleHealthDropboxIngestor(AppleHealthIngestor):
    """Import Apple Health exports stored in Dropbox into Postgres."""

    def __init__(
        self,
        *,
        dal: PostgresDal,
        client: AppleDropboxClient,
        parser: AppleHealthParser | None = None,
        writer_factory: type[AppleHealthWriter] | None = None,
    ) -> None:
        self._dal = dal
        self._client = client
        self._parser = parser or AppleHealthParser()
        self._writer_factory = writer_factory or AppleHealthWriter

    def ingest(self) -> AppleHealthIngestResult:
        try:
            return self._run_ingest()
        except AppleIngestError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            raise AppleIngestError(stage="unexpected", reason=str(exc)) from exc

    def get_last_import_timestamp(self) -> datetime | None:
        try:
            with self._dal.connection() as conn:
                writer = self._writer_factory(conn)
                timestamp = writer.get_last_import_timestamp()
        except Exception as exc:
            raise AppleIngestError(stage="checkpoint", reason=str(exc)) from exc

        if timestamp and timestamp.tzinfo is None:
            return timestamp.replace(tzinfo=timezone.utc)
        return timestamp

    # The heavy lifting lives in a helper to keep exception boundaries tight.
    def _run_ingest(self) -> AppleHealthIngestResult:
        all_processed_files: list[str] = []
        total_workouts = 0
        total_daily_points = 0

        try:
            connection_context = self._dal.connection()
        except Exception as exc:
            raise AppleIngestError(stage="connection", reason=str(exc)) from exc

        with connection_context as conn:
            try:
                writer = self._writer_factory(conn)
            except Exception as exc:
                raise AppleIngestError(stage="initialise_writer", reason=str(exc)) from exc

            try:
                last_import_time = writer.get_last_import_timestamp() or datetime(1970, 1, 1, tzinfo=timezone.utc)
            except Exception as exc:
                raise AppleIngestError(stage="checkpoint", reason=str(exc)) from exc

            try:
                new_health_files = self._client.find_new_export_files(
                    self._client.health_metrics_path,
                    last_import_time,
                )
                new_workout_files = self._client.find_new_export_files(
                    self._client.workouts_path,
                    last_import_time,
                )
            except Exception as exc:
                raise AppleIngestError(stage="discover_exports", reason=str(exc)) from exc

            all_new_files = sorted(new_health_files + new_workout_files, key=lambda item: item[0])

            if not all_new_files:
                log_utils.info("No new files to import.")
                summary = AppleHealthImportSummary(
                    sources=[],
                    workouts=0,
                    daily_points=0,
                    hr_days=0,
                    sleep_days=0,
                )
                return AppleHealthIngestResult(
                    success=True,
                    summary=summary,
                    failures=(),
                    statuses={"Apple Health": "ok"},
                    alerts=(),
                )

            log_utils.info(f"Found {len(all_new_files)} new file(s) to process.")

            for file_modified_time, file_path in all_new_files:
                log_utils.info(f"Processing file: {file_path} (modified: {file_modified_time})")

                content = self._download_file(file_path)
                json_data = _get_json_from_content(file_path, content)

                if not json_data:
                    log_utils.warn(f"Skipping file {file_path} as no JSON data could be extracted.")
                    continue

                root = {
                    "data": {
                        "metrics": json_data.get("data", {}).get("metrics", []),
                        "workouts": json_data.get("data", {}).get("workouts", []),
                    }
                }

                try:
                    parsed = self._parser.parse(root)
                except Exception as exc:
                    raise AppleIngestError(stage="parse", reason=str(exc), file_path=file_path) from exc

                try:
                    writer.upsert_all(parsed)
                except Exception as exc:
                    raise AppleIngestError(stage="write", reason=str(exc), file_path=file_path) from exc

                all_processed_files.append(file_path)
                total_workouts += len(parsed.get("workout_headers", []))
                total_daily_points += len(parsed.get("daily_metric_points", []))

            if all_processed_files:
                latest_file_timestamp = all_new_files[-1][0]
                try:
                    writer.save_last_import_timestamp(latest_file_timestamp)
                except Exception as exc:
                    raise AppleIngestError(stage="checkpoint", reason=str(exc)) from exc

            try:
                conn.commit()
            except Exception as exc:
                raise AppleIngestError(stage="commit", reason=str(exc)) from exc

        summary = AppleHealthImportSummary(
            sources=tuple(all_processed_files),
            workouts=total_workouts,
            daily_points=total_daily_points,
            hr_days=0,
            sleep_days=0,
        )

        return AppleHealthIngestResult(
            success=True,
            summary=summary,
            failures=(),
            statuses={"Apple Health": "ok"},
            alerts=(),
        )

    def _download_file(self, path: str) -> bytes:
        try:
            return self._client.download_as_bytes(path)
        except Exception as exc:
            raise AppleIngestError(stage="download", reason=str(exc), file_path=path) from exc


def build_ingestor(
    *,
    dal: Optional[PostgresDal] = None,
    client: Optional[AppleDropboxClient] = None,
    parser: Optional[AppleHealthParser] = None,
    writer_factory: type[AppleHealthWriter] | None = None,
) -> AppleHealthDropboxIngestor:
    """Convenience helper used by the DI container."""

    return AppleHealthDropboxIngestor(
        dal=dal or PostgresDal(),
        client=client or AppleDropboxClient(),
        parser=parser,
        writer_factory=writer_factory,
    )


__all__ = [
    "AppleHealthDropboxIngestor",
    "AppleIngestError",
    "AppleHealthIngestor",
    "AppleHealthIngestResult",
    "AppleHealthImportSummary",
    "_get_json_from_content",
    "build_ingestor",
]

