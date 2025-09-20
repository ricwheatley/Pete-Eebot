# pete_e/application/apple_dropbox_ingest.py

import io
import json
import logging
import zipfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

from pete_e.infrastructure.database import get_conn
from pete_e.infrastructure.apple_dropbox_client import AppleDropboxClient
from pete_e.infrastructure.apple_parser import AppleHealthParser
from pete_e.infrastructure.apple_writer import AppleHealthWriter

# British English comments and docstrings.

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")


@dataclass
class ImportReport:
    """A summary of the data imported from the export files."""
    sources: List[str]
    workouts: int
    daily_points: int
    hr_days: int
    sleep_days: int


def _normalise_device_name(name: str) -> str:
    """Normalises fancy apostrophes and non-breaking spaces from Apple sources."""
    return name.replace("\u2019", "'").replace("\xa0", " ").strip()


def _get_json_from_content(path: str, content_bytes: bytes) -> Optional[Dict]:
    """
    Extracts JSON data from the given content, handling both raw JSON and zipped JSON files.
    """
    try:
        # FIX: Check the file extension to determine how to process the content.
        if path.lower().endswith(".zip"):
            logging.info(f"Extracting JSON from zip file: {path}")
            with io.BytesIO(content_bytes) as bio:
                with zipfile.ZipFile(bio, 'r') as zf:
                    json_files = [f for f in zf.namelist() if f.endswith('.json')]
                    if not json_files:
                        logging.warning(f"No JSON file found in the zip archive: {path}")
                        return None
                    with zf.open(json_files[0]) as json_file:
                        return json.load(json_file)
        elif path.lower().endswith(".json"):
            logging.info(f"Parsing raw JSON file: {path}")
            return json.loads(content_bytes)
        else:
            logging.warning(f"Unsupported file type encountered: {path}. Only .zip and .json are supported.")
            return None
    except (zipfile.BadZipFile, json.JSONDecodeError) as e:
        logging.error(f"Failed to extract or parse JSON from file {path}: {e}")
        return None


def run_apple_health_ingest() -> ImportReport:
    """
    Orchestrates importing all new Apple Health data from Dropbox since the last run.
    """
    
    client = AppleDropboxClient()
    parser = AppleHealthParser()

    all_processed_files = []
    total_workouts = 0
    total_daily_points = 0
    
    # Use a single database connection for the entire operation
    with get_conn() as conn:
        writer = AppleHealthWriter(conn)

        # 1. Get the timestamp of the last successful import.
        # Default to a very old date if this is the first ever run.
        last_import_time = writer.get_last_import_timestamp() or datetime(1970, 1, 1, tzinfo=timezone.utc)
        
        # 2. Find all new files from Dropbox since that time.
        new_health_files = client.find_new_export_files(client.health_metrics_path, last_import_time)
        new_workout_files = client.find_new_export_files(client.workouts_path, last_import_time)
        
        # Combine and sort all files by their modification time to ensure chronological processing.
        all_new_files = sorted(new_health_files + new_workout_files, key=lambda item: item[0])

        if not all_new_files:
            logging.info("No new files to import.")
            return ImportReport(sources=[], workouts=0, daily_points=0, hr_days=0, sleep_days=0)

        logging.info(f"Found {len(all_new_files)} new file(s) to process.")

        # 3. Process each new file one by one.
        for file_modified_time, file_path in all_new_files:
            logging.info(f"Processing file: {file_path} (modified: {file_modified_time})")
            
            content = client.download_as_bytes(file_path)
            json_data = _get_json_from_content(file_path, content)

            if not json_data:
                logging.warning(f"Skipping file {file_path} as no JSON data could be extracted.")
                continue

            # In this new model, each file is self-contained.
            # We assume a file has either 'metrics' or 'workouts', but not both.
            root = {"data": {
                "metrics": json_data.get("data", {}).get("metrics", []),
                "workouts": json_data.get("data", {}).get("workouts", []),
            }}

            parsed = parser.parse(root)
            writer.upsert_all(parsed) # This writes the data for the current file
            
            all_processed_files.append(file_path)
            total_workouts += len(parsed.get("workout_headers", []))
            total_daily_points += len(parsed.get("daily_metric_points", []))

        # 4. After all files are processed successfully, save the new checkpoint.
        latest_file_timestamp = all_new_files[-1][0]
        writer.save_last_import_timestamp(latest_file_timestamp)
        
        # Finally, commit the entire transaction.
        conn.commit()
        logging.info("Database transaction committed successfully.")

    # A simple report based on the looped processing.
    report = ImportReport(
        sources=all_processed_files,
        workouts=total_workouts,
        daily_points=total_daily_points,
        hr_days=0, # Note: a full report would require querying the DB post-import
        sleep_days=0,
    )
    return report


if __name__ == "__main__":
    """Simple CLI runner for convenience."""
    try:
        report = run_apple_health_ingest()
        logging.info("--- Import Summary ---")
        logging.info(f"Source files: {', '.join(report.sources)}")
        logging.info(f"Workouts:     {report.workouts}")
        logging.info(f"Metric points: {report.daily_points}")
        logging.info(f"HR days:      {report.hr_days}")
        logging.info(f"Sleep days:   {report.sleep_days}")
        logging.info("Import complete.")
    except (FileNotFoundError, ValueError, IOError) as e:
        logging.error(f"Import failed: {e}")
        raise SystemExit(1)

