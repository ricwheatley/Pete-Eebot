# pete_e/infrastructure/apple_dropbox_client.py

import logging
import os
import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import dropbox
from dropbox.exceptions import AuthError
from dropbox.files import FileMetadata, ListFolderResult

# British English comments and docstrings.


class AppleDropboxClient:
    """A robust client for finding and downloading HealthAutoExport files from Dropbox."""

    def __init__(self):
        """Initialises the client and authenticates with Dropbox."""
        token = os.environ.get("DROPBOX_TOKEN")
        if not token:
            raise ValueError("DROPBOX_TOKEN environment variable is not set.")

        health_path = os.environ.get("DROPBOX_HEALTH_METRICS_DIR", "").strip()
        workouts_path = os.environ.get("DROPBOX_WORKOUTS_DIR", "").strip()

        if not health_path:
            raise ValueError("DROPBOX_HEALTH_METRICS_DIR environment variable is not set.")
        if not workouts_path:
            raise ValueError("DROPBOX_WORKOUTS_DIR environment variable is not set.")

        self.health_metrics_path = health_path if health_path.startswith('/') else f"/{health_path}"
        self.workouts_path = workouts_path if workouts_path.startswith('/') else f"/{workouts_path}"

        try:
            self.dbx = dropbox.Dropbox(token)
            self.dbx.users_get_current_account()
            logging.info("Successfully connected to Dropbox.")
        except AuthError:
            logging.error("Dropbox authentication failed. The token is invalid or expired.")
            raise ValueError("Invalid DROPBOX_TOKEN.")

    def _get_all_files(self, folder_path: str) -> List[FileMetadata]:
        """Handles Dropbox API pagination to fetch all files from the specified folder."""
        all_entries = []
        try:
            result: ListFolderResult = self.dbx.files_list_folder(folder_path, recursive=False)
            while True:
                all_entries.extend(
                    entry
                    for entry in result.entries
                    if isinstance(entry, FileMetadata)
                )
                if not result.has_more:
                    break
                result = self.dbx.files_list_folder_continue(result.cursor)
            return all_entries
        except dropbox.exceptions.ApiError as e:
            logging.error(f"Error listing Dropbox folder '{folder_path}': {e}")
            raise IOError(f"Could not list files in Dropbox folder: {e}") from e

    def find_new_export_files(self, folder_path: str, since_datetime: datetime) -> List[Tuple[datetime, str]]:
        """
        Finds all export files in a folder that have been modified after a given datetime.
        Returns a list of (modification_time, file_path) sorted chronologically.
        """
        logging.info(f"Searching for new files since {since_datetime.isoformat()} in '{folder_path}'")
        all_files = self._get_all_files(folder_path)
        
        new_files = []
        for entry in all_files:
            is_export_file = entry.name.startswith("HealthAutoExport") and entry.name.lower().endswith((".json", ".zip"))
            
            modified_time = entry.client_modified
            
            if modified_time.tzinfo is None:
                modified_time = modified_time.replace(tzinfo=timezone.utc)

            if is_export_file and modified_time > since_datetime:
                new_files.append((modified_time, entry.path_display))
        
        new_files.sort(key=lambda item: item[0])
        
        logging.info(f"Found {len(new_files)} new files in '{folder_path}'.")
        return new_files

    def download_as_bytes(self, dropbox_path: str) -> bytes:
        """Downloads the specified file and returns its content as bytes."""
        logging.info(f"Downloading {dropbox_path} from Dropbox...")
        try:
            _, res = self.dbx.files_download(dropbox_path)
            logging.info("Download successful.")
            return res.content
        except dropbox.exceptions.ApiError as e:
            logging.error(f"Failed to download {dropbox_path}: {e}")
            raise IOError(f"Could not download file from Dropbox: {e}") from e
        
    def find_new_files_since(self, folder_path: str, since_datetime: datetime) -> List[Tuple[datetime, str]]:
        """Finds all export files in a folder modified after a given datetime."""
        logging.info(f"Searching for new files since {since_datetime} in '{folder_path}'")
        all_files = self._get_all_files(folder_path)
        
        new_files = []
        for entry in all_files:
            is_export_file = entry.name.startswith("HealthAutoExport") and entry.name.lower().endswith((".json", ".zip"))
            
            if is_export_file and entry.client_modified > since_datetime:
                new_files.append((entry.client_modified, entry.path_display))
        
        # Sort files by modification date to process them in the correct order
        new_files.sort(key=lambda item: item[0])
        return new_files

