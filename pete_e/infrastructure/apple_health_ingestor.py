"""Infrastructure implementation for importing Apple Health data."""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional

from pete_e.domain.daily_sync import (
    AppleHealthIngestFailure,
    AppleHealthImportSummary,
    AppleHealthIngestResult,
    AppleHealthIngestor,
)
from pete_e.infrastructure import log_utils
from pete_e.infrastructure.apple_dropbox_client import AppleDropboxClient
from pete_e.infrastructure.apple_ingest_coordinator import (
    AppleFileOutcome,
    AppleIngestDecision,
    AppleIngestSource,
    AppleTimestampGroup,
    AppleTimestampGroupOutcome,
    decide_ingest,
    failed_ingest_decision,
    failure_alert,
    group_discovered_files,
    normalise_failure_reason,
    normalise_timestamp,
    safe_exception_reason,
)
from pete_e.infrastructure.apple_parser import AppleHealthParser, AppleParseResult
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

    def _run_ingest(self) -> AppleHealthIngestResult:
        try:
            connection_context = self._dal.connection()
        except Exception as exc:
            raise AppleIngestError(stage="connection", reason=str(exc)) from exc

        with connection_context as conn:
            writer = self._create_writer(conn)
            last_import_time = self._read_checkpoint(writer)
            groups = self._discover_groups(last_import_time)
            if not groups:
                log_utils.info("No new files to import.")
            else:
                file_count = sum(len(group.sources) for group in groups)
                log_utils.info(f"Found {file_count} new file(s) to process.")
            group_outcomes = tuple(
                self._process_group(writer, group) for group in groups
            )
            decision = decide_ingest(last_import_time, group_outcomes)
            self._apply_transaction_decision(conn, writer, decision)

        return self._result_from_decision(decision)
        """Perform run ingest."""

    def _create_writer(self, conn) -> AppleHealthWriter:
        try:
            return self._writer_factory(conn)
        except Exception as exc:
            raise AppleIngestError(stage="initialise_writer", reason=str(exc)) from exc

    def _read_checkpoint(self, writer: AppleHealthWriter) -> datetime:
        try:
            checkpoint = writer.get_last_import_timestamp() or datetime(
                1970, 1, 1, tzinfo=timezone.utc
            )
            return self._normalise_timestamp(checkpoint)
        except Exception as exc:
            raise AppleIngestError(stage="checkpoint", reason=str(exc)) from exc

    def _discover_groups(
        self,
        last_import_time: datetime,
    ) -> tuple[AppleTimestampGroup, ...]:
        try:
            health_files = self._client.find_new_export_files(
                self._client.health_metrics_path,
                last_import_time,
            )
            workout_files = self._client.find_new_export_files(
                self._client.workouts_path,
                last_import_time,
            )
        except Exception as exc:
            raise AppleIngestError(stage="discover_exports", reason=str(exc)) from exc
        return group_discovered_files(health_files, workout_files)

    def _process_group(
        self,
        writer: AppleHealthWriter,
        group: AppleTimestampGroup,
    ) -> AppleTimestampGroupOutcome:
        outcomes: list[AppleFileOutcome] = []
        for source in group.sources:
            log_utils.info(
                f"Processing file: {source.path} (modified: {source.modified_at})"
            )
            outcomes.append(self._process_file(writer, source))
        return AppleTimestampGroupOutcome(group.modified_at, tuple(outcomes))

    def _process_file(
        self,
        writer: AppleHealthWriter,
        source: AppleIngestSource,
    ) -> AppleFileOutcome:
        try:
            root = self._extract_source(source)
            parsed, failure = self._parse_source(source, root)
        except AppleIngestError as exc:
            failure = self._failure_from_error(exc, modified_at=source.modified_at)
            self._log_failure(failure)
            return AppleFileOutcome(source=source, processed=False, failure=failure)

        if failure is not None:
            self._log_failure(failure)
        self._write_source(writer, source, parsed)
        return AppleFileOutcome(
            source=source,
            processed=True,
            workouts=len(parsed.get("workout_headers", [])),
            daily_points=len(parsed.get("daily_metric_points", [])),
            failure=failure,
        )

    def _extract_source(self, source: AppleIngestSource) -> dict[str, object]:
        content = self._download_file(source.path)
        try:
            json_data = _get_json_from_content(source.path, content)
        except Exception as exc:  # pragma: no cover - defensive extraction boundary
            raise AppleIngestError(
                stage="extract",
                reason=self._safe_reason(exc),
                file_path=source.path,
            ) from exc

        if json_data is None or not isinstance(json_data, dict):
            raise AppleIngestError(
                stage="extract",
                reason="no extractable JSON object",
                file_path=source.path,
            )
        json_root = json_data.get("data", {})
        if not isinstance(json_root, dict):
            raise AppleIngestError(
                stage="extract",
                reason="JSON data field is not an object",
                file_path=source.path,
            )
        return {
            "data": {
                "metrics": json_root.get("metrics", []),
                "workouts": json_root.get("workouts", []),
            }
        }

    def _parse_source(
        self,
        source: AppleIngestSource,
        root: object,
    ) -> tuple[AppleParseResult, AppleHealthIngestFailure | None]:
        try:
            parsed = self._parser.parse(root)
        except Exception as exc:
            raise AppleIngestError(
                stage="parse",
                reason=self._safe_reason(exc),
                file_path=source.path,
            ) from exc

        skipped_row_count = int(parsed.get("skipped_row_count", 0) or 0)
        failure = None
        if skipped_row_count:
            failure = AppleHealthIngestFailure(
                stage="parse",
                reason=f"parser skipped {skipped_row_count} invalid row(s)",
                file_path=source.path,
                modified_at=source.modified_at,
            )
        return parsed, failure

    def _write_source(
        self,
        writer: AppleHealthWriter,
        source: AppleIngestSource,
        parsed: AppleParseResult,
    ) -> None:
        try:
            writer.upsert_all(parsed)
        except Exception as exc:
            # A PostgreSQL statement error aborts the transaction, so the only
            # safe response is to roll back this run rather than continue.
            raise AppleIngestError(
                stage="write",
                reason=self._safe_reason(exc),
                file_path=source.path,
                modified_at=source.modified_at,
            ) from exc

    def _apply_transaction_decision(
        self,
        conn,
        writer: AppleHealthWriter,
        decision: AppleIngestDecision,
    ) -> None:
        if decision.checkpoint_to_save is not None:
            try:
                writer.save_last_import_timestamp(decision.checkpoint_to_save)
            except Exception as exc:
                raise AppleIngestError(
                    stage="checkpoint",
                    reason=self._safe_reason(exc),
                ) from exc
        if decision.commit_required:
            try:
                conn.commit()
            except Exception as exc:
                raise AppleIngestError(stage="commit", reason=str(exc)) from exc

    @staticmethod
    def _result_from_decision(decision: AppleIngestDecision) -> AppleHealthIngestResult:
        sources = [] if decision.is_no_work else decision.processed_sources
        return AppleHealthIngestResult(
            success=decision.success,
            summary=AppleHealthImportSummary(
                sources=sources,
                workouts=decision.workouts,
                daily_points=decision.daily_points,
                hr_days=0,
                sleep_days=0,
            ),
            failures=decision.source_failures,
            statuses={"Apple Health": decision.status},
            alerts=decision.alerts,
            failure_details=decision.failure_details,
        )

    def _download_file(self, path: str) -> bytes:
        try:
            return self._client.download_as_bytes(path)
        except Exception as exc:
            raise AppleIngestError(
                stage="download", reason=str(exc), file_path=path
            ) from exc
        """Perform download file."""

    @staticmethod
    def _normalise_timestamp(timestamp: datetime) -> datetime:
        return normalise_timestamp(timestamp)

    @staticmethod
    def _safe_reason(exc: BaseException) -> str:
        return safe_exception_reason(exc)

    @classmethod
    def _failure_from_error(
        cls,
        error: AppleIngestError,
        *,
        modified_at: datetime | None = None,
    ) -> AppleHealthIngestFailure:
        return AppleHealthIngestFailure(
            stage=error.stage,
            reason=normalise_failure_reason(error.reason, fallback=error.stage),
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
        return failure_alert(failures, partial=partial)

    @classmethod
    def _failed_result(
        cls,
        failure: AppleHealthIngestFailure,
    ) -> AppleHealthIngestResult:
        return cls._result_from_decision(failed_ingest_decision(failure))


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
