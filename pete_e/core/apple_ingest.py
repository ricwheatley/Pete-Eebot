"""
Ingest and process Apple Health export data received via Tailscale.
"""
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile, is_zipfile

# Use settings for configurable paths
from pete_e.config import settings
from pete_e.infra import log_utils

# The new location for the processing function
from pete_e.core.apple_client import process_apple_health_export

def check_dependencies():
    """Verify that the Tailscale CLI is installed."""
    if not shutil.which("tailscale"):
        log_utils.log_message(
            "CRITICAL: `tailscale` command not found. Please install it and ensure it's in your PATH.",
            "ERROR"
        )
        sys.exit(1)

def ingest_and_process_apple_data() -> bool:
    """
    Orchestrates the process of receiving, unzipping, and processing Apple Health data.
    - Checks for Tailscale CLI.
    - Creates necessary directories if they don't exist.
    - Fetches the latest zip file from Tailscale inbox.
    - Processes the data and archives the zip.
    """
    log_utils.log_message("Starting Apple Health data ingestion...", "INFO")
    check_dependencies()

    # Ensure directories exist, using paths from config
    incoming_dir = settings.apple_incoming_path
    processed_dir = settings.apple_processed_path
    incoming_dir.mkdir(exist_ok=True)
    processed_dir.mkdir(exist_ok=True)

    # --- Get the file from Tailscale ---
    log_utils.log_message(f"Checking for incoming files in Tailscale inbox...", "INFO")
    try:
        # This command will move the file from the Tailscale inbox to our incoming dir
        subprocess.run(
            ["tailscale", "file", "get", str(incoming_dir)],
            check=True,
            capture_output=True,
            text=True
        )
    except FileNotFoundError:
        log_utils.log_message(
            "`tailscale` command not found while attempting to fetch files."
            " Please install the Tailscale CLI and ensure it is on your PATH.",
            "ERROR",
        )
        return False
    except subprocess.CalledProcessError as e:
        stderr_output = e.stderr or ""
        stdout_output = e.stdout or ""

        if isinstance(stderr_output, bytes):
            stderr_output = stderr_output.decode(errors="replace")
        if isinstance(stdout_output, bytes):
            stdout_output = stdout_output.decode(errors="replace")

        combined_output = "\n".join(
            part for part in (stdout_output.strip(), stderr_output.strip()) if part
        )
        error_text = combined_output or str(e)

        if "no files" in error_text.lower():
            log_utils.log_message("No new files found in Tailscale inbox.", "INFO")
            return True  # Not an error, just nothing to do

        log_utils.log_message(
            f"Error fetching file with Tailscale: {error_text}",
            "ERROR",
        )
        return False

    # --- Find the newest zip file ---
    try:
        zip_files = list(incoming_dir.glob("*.zip"))
        if not zip_files:
            log_utils.log_message("No zip files found in the incoming directory after fetch.", "INFO")
            return True

        latest_zip = max(zip_files, key=lambda p: p.stat().st_mtime)
        log_utils.log_message(f"Found new health data file: {latest_zip.name}", "INFO")

    except Exception as e:
        log_utils.log_message(f"Error finding latest zip file: {e}", "ERROR")
        return False

    # --- Process the zip file ---
    if is_zipfile(latest_zip):
        try:
            # Re-using the existing processing logic from apple_client
            process_apple_health_export(str(latest_zip))

            # --- Archive the processed file ---
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_name = f"{latest_zip.stem}_{timestamp}.zip"
            shutil.move(latest_zip, processed_dir / archive_name)
            log_utils.log_message(f"Successfully processed and archived to {archive_name}", "INFO")
            return True

        except Exception as e:
            log_utils.log_message(f"Failed to process Apple Health export '{latest_zip.name}': {e}", "ERROR")
            # Optionally, move to a 'failed' directory instead of stopping
            return False
    else:
        log_utils.log_message(f"File '{latest_zip.name}' is not a valid zip file.", "WARN")
        return False

if __name__ == "__main__":
    # This allows running the script directly for testing, but the goal is to call
    # ingest_and_process_apple_data() from the main CLI.
    success = ingest_and_process_apple_data()
    sys.exit(0 if success else 1)
