"""Infrastructure implementation for importing Apple Health data."""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import groupby
from typing import Dict, Optional

from pete_e.domain.daily_sync import (
    AppleHealthIngestFailure,
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
    modified_at: Optional[datetime] = None

    def __post_init__(self) -> None:  # pragma: no cover - simple data plumbing
        super().__init__(self._compose_message())
        """Implement the `__post_init__` dunder method behavior."""

    def _compose_message(self) -> str:
        parts = [self.stage, self.reason]
        message = " - ".join(part for part in parts if part)
        if self.file_path:
            message = f"{message} [{self.file_path}]"
        return message
        """Perform compose message."""

    def __str__(self) -> str:  # pragma: no cover - defers to _compose_message
        return self._compose_message()
        """Implement the `__str__` dunder method behavior."""


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
        """Initialize this object."""

    def ingest(self) -> AppleHealthIngestResult:
        try:
            return self._run_ingest()
        except AppleIngestError as exc:
            failure = self._failure_from_error(exc)
            self._log_failure(failure)
            return self._failed_result(failure)
        except Exception as exc:  # pragma: no cover - defensive
            failure = AppleHealthIngestFailure(
                stage="unexpected",
                reason=self._safe_reason(exc),
            )
            self._log_failure(failure)
            return self._failed_result(failure)
        """Perform ingest."""

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
        """Perform get last import timestamp."""

    # The heavy lifting lives in a helper to keep exception boundaries tight.
    def _run_ingest(self) -> AppleHealthIngestResult:
        all_processed_files: list[str] = []
        file_failures: list[AppleHealthIngestFailure] = []
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
                last_import_time = self._normalise_timestamp(
                    writer.get_last_import_timestamp()
                    or datetime(1970, 1, 1, tzinfo=timezone.utc)
                )
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

            all_new_files = [
                (self._normalise_timestamp(modified_at), str(file_path))
                for modified_at, file_path in new_health_files + new_workout_files
            ]
            all_new_files.sort(key=lambda item: (item[0], item[1].casefold(), item[1]))

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

            safe_watermark = last_import_time
            watermark_blocked = False

            # The persisted checkpoint contains only a timestamp and discovery
            # is exclusive (client_modified > checkpoint). Treat every equal-
            # timestamp group as indivisible so a collision cannot hide a
            # failed peer. Later successes may be committed, but remain
            # replayable until the earlier failure is corrected.
            for file_modified_time, timestamp_group in groupby(
                all_new_files,
                key=lambda item: item[0],
            ):
                group_failed = False
                for _, file_path in timestamp_group:
                    log_utils.info(
                        f"Processing file: {file_path} (modified: {file_modified_time})"
                    )

                    try:
                        content = self._download_file(file_path)
                    except AppleIngestError as exc:
                        failure = self._failure_from_error(
                            exc,
                            modified_at=file_modified_time,
                        )
                        file_failures.append(failure)
                        self._log_failure(failure)
                        group_failed = True
                        continue

                    try:
                        json_data = _get_json_from_content(file_path, content)
                    except Exception as exc:  # pragma: no cover - defensive extraction boundary
                        failure = AppleHealthIngestFailure(
                            stage="extract",
                            reason=self._safe_reason(exc),
                            file_path=file_path,
                            modified_at=file_modified_time,
                        )
                        file_failures.append(failure)
                        self._log_failure(failure)
                        group_failed = True
                        continue

                    if json_data is None or not isinstance(json_data, dict):
                        failure = AppleHealthIngestFailure(
                            stage="extract",
                            reason="no extractable JSON object",
                            file_path=file_path,
                            modified_at=file_modified_time,
                        )
                        file_failures.append(failure)
                        self._log_failure(failure)
                        group_failed = True
                        continue

                    json_root = json_data.get("data", {})
                    if not isinstance(json_root, dict):
                        failure = AppleHealthIngestFailure(
                            stage="extract",
                            reason="JSON data field is not an object",
                            file_path=file_path,
                            modified_at=file_modified_time,
                        )
                        file_failures.append(failure)
                        self._log_failure(failure)
                        group_failed = True
                        continue

                    root = {
                        "data": {
                            "metrics": json_root.get("metrics", []),
                            "workouts": json_root.get("workouts", []),
                        }
                    }

                    try:
                        parsed = self._parser.parse(root)
                    except Exception as exc:
                        failure = AppleHealthIngestFailure(
                            stage="parse",
                            reason=self._safe_reason(exc),
                            file_path=file_path,
                            modified_at=file_modified_time,
                        )
                        file_failures.append(failure)
                        self._log_failure(failure)
                        group_failed = True
                        continue

                    skipped_row_count = int(parsed.get("skipped_row_count", 0) or 0)
                    if skipped_row_count:
                        failure = AppleHealthIngestFailure(
                            stage="parse",
                            reason=f"parser skipped {skipped_row_count} invalid row(s)",
                            file_path=file_path,
                            modified_at=file_modified_time,
                        )
                        file_failures.append(failure)
                        self._log_failure(failure)
                        group_failed = True

                    try:
                        writer.upsert_all(parsed)
                    except Exception as exc:
                        # A PostgreSQL statement error aborts the transaction,
                        # so the only safe response is to roll back this entire
                        # run rather than continue with later files.
                        raise AppleIngestError(
                            stage="write",
                            reason=self._safe_reason(exc),
                            file_path=file_path,
                            modified_at=file_modified_time,
                        ) from exc

                    all_processed_files.append(file_path)
                    total_workouts += len(parsed.get("workout_headers", []))
                    total_daily_points += len(parsed.get("daily_metric_points", []))

                if group_failed:
                    watermark_blocked = True
                elif not watermark_blocked:
                    safe_watermark = file_modified_time

            if safe_watermark > last_import_time:
                try:
                    writer.save_last_import_timestamp(safe_watermark)
                except Exception as exc:
                    raise AppleIngestError(
                        stage="checkpoint",
                        reason=self._safe_reason(exc),
                    ) from exc

            if all_processed_files or safe_watermark > last_import_time:
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

        partial = bool(file_failures and all_processed_files)
        return AppleHealthIngestResult(
            success=not file_failures,
            summary=summary,
            failures=("Apple Health",) if file_failures else (),
            statuses={
                "Apple Health": "partial" if partial else "failed" if file_failures else "ok"
            },
            alerts=(self._file_failure_alert(file_failures, partial=partial),)
            if file_failures
            else (),
            failure_details=tuple(file_failures),
        )
        """Perform run ingest."""

    def _download_file(self, path: str) -> bytes:
        try:
            return self._client.download_as_bytes(path)
        except Exception as exc:
            raise AppleIngestError(stage="download", reason=str(exc), file_path=path) from exc
        """Perform download file."""

    @staticmethod
    def _normalise_timestamp(timestamp: datetime) -> datetime:
        if timestamp.tzinfo is None:
            return timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone.utc)

    @staticmethod
    def _safe_reason(exc: BaseException) -> str:
        reason = " ".join(str(exc).split()) or type(exc).__name__
        return reason[:240]

    @classmethod
    def _failure_from_error(
        cls,
        error: AppleIngestError,
        *,
        modified_at: datetime | None = None,
    ) -> AppleHealthIngestFailure:
        return AppleHealthIngestFailure(
            stage=error.stage,
            reason=" ".join(error.reason.split())[:240] or error.stage,
            file_path=error.file_path,
            modified_at=modified_at or error.modified_at,
        )

    @staticmethod
    def _log_failure(failure: AppleHealthIngestFailure) -> None:
        identity = failure.file_path or "ingest run"
        log_utils.error(
            f"Apple Health ingest failure at {failure.stage} for {identity}: {failure.reason}"
        )

    @staticmethod
    def _file_failure_alert(
        failures: list[AppleHealthIngestFailure],
        *,
        partial: bool,
    ) -> str:
        first = failures[0]
        identity = first.file_path or "ingest run"
        outcome = "partially completed" if partial else "failed"
        return (
            f"Apple Health ingest {outcome}; {len(failures)} failure(s) remain retryable. "
            f"First failure: {identity} at {first.stage} ({first.reason})."
        )

    @classmethod
    def _failed_result(
        cls,
        failure: AppleHealthIngestFailure,
    ) -> AppleHealthIngestResult:
        return AppleHealthIngestResult(
            success=False,
            summary=AppleHealthImportSummary(
                sources=(),
                workouts=0,
                daily_points=0,
                hr_days=0,
                sleep_days=0,
            ),
            failures=("Apple Health",),
            statuses={"Apple Health": "failed"},
            alerts=(cls._file_failure_alert([failure], partial=False),),
            failure_details=(failure,),
        )


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
    "AppleHealthIngestFailure",
    "AppleHealthDropboxIngestor",
    "AppleIngestError",
    "AppleHealthIngestor",
    "AppleHealthIngestResult",
    "AppleHealthImportSummary",
    "_get_json_from_content",
    "build_ingestor",
]

