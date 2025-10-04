# pete_e/application/apple_dropbox_ingest.py

import io
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pete_e.infrastructure.database import get_conn
from pete_e.infrastructure.apple_dropbox_client import AppleDropboxClient
from pete_e.infrastructure.apple_parser import AppleHealthParser
from pete_e.infrastructure.apple_writer import AppleHealthWriter

from pete_e.infrastructure import log_utils
# British English comments and docstrings.


@dataclass
class ImportReport:
    """A summary of the data imported from the export files."""
    sources: List[str]
    workouts: int
    daily_points: int
    hr_days: int
    sleep_days: int


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


def _normalise_device_name(name: str) -> str:
    """Normalises fancy apostrophes and non-breaking spaces from Apple sources."""
    return name.replace("\u2019", "'").replace("\xa0", " ").strip()


def _get_json_from_content(path: str, content_bytes: bytes) -> Optional[Dict]:
    """
    Extracts JSON data from the given content, handling both raw JSON and zipped JSON files.
    """
    try:
        if path.lower().endswith(".zip"):
            log_utils.info(f"Extracting JSON from zip file: {path}")
            with io.BytesIO(content_bytes) as bio:
                with zipfile.ZipFile(bio, 'r') as zf:
                    json_files = [f for f in zf.namelist() if f.endswith('.json')]
                    if not json_files:
                        log_utils.warn(f"No JSON file found in the zip archive: {path}")
                        return None
                    with zf.open(json_files[0]) as json_file:
                        return json.load(json_file)
        elif path.lower().endswith(".json"):
            log_utils.info(f"Parsing raw JSON file: {path}")
            return json.loads(content_bytes)
        else:
            log_utils.warn(f"Unsupported file type encountered: {path}. Only .zip and .json are supported.")
            return None
    except (zipfile.BadZipFile, json.JSONDecodeError) as e:
        log_utils.error(f"Failed to extract or parse JSON from file {path}: {e}")
        return None


def run_apple_health_ingest() -> ImportReport:
    """
    Orchestrates importing all new Apple Health data from Dropbox since the last run.
    """

    try:
        client = AppleDropboxClient()
        parser = AppleHealthParser()
    except Exception as exc:  # pragma: no cover - defensive
        raise AppleIngestError(stage="initialise", reason=str(exc)) from exc

    all_processed_files: List[str] = []
    total_workouts = 0
    total_daily_points = 0

    try:
        conn_ctx = get_conn()
    except Exception as exc:  # pragma: no cover - defensive
        raise AppleIngestError(stage="connection", reason=str(exc)) from exc

    try:
        with conn_ctx as conn:
            try:
                writer = AppleHealthWriter(conn)
            except Exception as exc:  # pragma: no cover - defensive
                raise AppleIngestError(stage="initialise_writer", reason=str(exc)) from exc

            try:
                last_import_time = writer.get_last_import_timestamp() or datetime(1970, 1, 1, tzinfo=timezone.utc)
            except Exception as exc:
                raise AppleIngestError(stage="checkpoint", reason=str(exc)) from exc

            try:
                new_health_files = client.find_new_export_files(client.health_metrics_path, last_import_time)
                new_workout_files = client.find_new_export_files(client.workouts_path, last_import_time)
            except Exception as exc:
                raise AppleIngestError(stage="discover_exports", reason=str(exc)) from exc

            all_new_files = sorted(new_health_files + new_workout_files, key=lambda item: item[0])

            if not all_new_files:
                log_utils.info("No new files to import.")
                return ImportReport(sources=[], workouts=0, daily_points=0, hr_days=0, sleep_days=0)

            log_utils.info(f"Found {len(all_new_files)} new file(s) to process.")

            for file_modified_time, file_path in all_new_files:
                log_utils.info(f"Processing file: {file_path} (modified: {file_modified_time})")

                try:
                    content = client.download_as_bytes(file_path)
                except Exception as exc:
                    raise AppleIngestError(stage="download", reason=str(exc), file_path=file_path) from exc

                json_data = _get_json_from_content(file_path, content)

                if not json_data:
                    log_utils.warn(f"Skipping file {file_path} as no JSON data could be extracted.")
                    continue

                root = {"data": {
                    "metrics": json_data.get("data", {}).get("metrics", []),
                    "workouts": json_data.get("data", {}).get("workouts", []),
                }}

                try:
                    parsed = parser.parse(root)
                except Exception as exc:
                    raise AppleIngestError(stage="parse", reason=str(exc), file_path=file_path) from exc

                try:
                    writer.upsert_all(parsed)
                except Exception as exc:
                    raise AppleIngestError(stage="write", reason=str(exc), file_path=file_path) from exc

                all_processed_files.append(file_path)
                total_workouts += len(parsed.get("workout_headers", []))
                total_daily_points += len(parsed.get("daily_metric_points", []))

            latest_file_timestamp = all_new_files[-1][0]
            try:
                writer.save_last_import_timestamp(latest_file_timestamp)
            except Exception as exc:
                raise AppleIngestError(stage="checkpoint", reason=str(exc)) from exc

            try:
                conn.commit()
            except Exception as exc:
                raise AppleIngestError(stage="commit", reason=str(exc)) from exc
    except AppleIngestError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise AppleIngestError(stage="unexpected", reason=str(exc)) from exc

    report = ImportReport(
        sources=all_processed_files,
        workouts=total_workouts,
        daily_points=total_daily_points,
        hr_days=0,
        sleep_days=0,
    )
    return report



def get_last_successful_import_timestamp() -> Optional[datetime]:
    """Fetches the timestamp of the latest completed Apple Health import."""
    try:
        conn_ctx = get_conn()
    except Exception as exc:  # pragma: no cover - defensive
        raise AppleIngestError(stage="connection", reason=str(exc)) from exc

    try:
        with conn_ctx as conn:
            try:
                writer = AppleHealthWriter(conn)
            except Exception as exc:  # pragma: no cover - defensive
                raise AppleIngestError(stage="initialise_writer", reason=str(exc)) from exc

            try:
                last_import = writer.get_last_import_timestamp()
            except Exception as exc:
                raise AppleIngestError(stage="checkpoint", reason=str(exc)) from exc
    except AppleIngestError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise AppleIngestError(stage="unexpected", reason=str(exc)) from exc

    if last_import and last_import.tzinfo is None:
        last_import = last_import.replace(tzinfo=timezone.utc)

    return last_import


if __name__ == "__main__":
    """Simple CLI runner for convenience."""
    try:
        report = run_apple_health_ingest()
        log_utils.info("--- Import Summary ---")
        log_utils.info(f"Source files: {', '.join(report.sources)}")
        log_utils.info(f"Workouts:     {report.workouts}")
        log_utils.info(f"Metric points: {report.daily_points}")
        log_utils.info(f"HR days:      {report.hr_days}")
        log_utils.info(f"Sleep days:   {report.sleep_days}")
        log_utils.info("Import complete.")
    except (FileNotFoundError, ValueError, IOError) as e:
        log_utils.error(f"Import failed: {e}")
        raise SystemExit(1)

