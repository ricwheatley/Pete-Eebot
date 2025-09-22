# pete_e/infrastructure/apple_dropbox_client.py

import logging
import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import dropbox
from dropbox.exceptions import AuthError, DropboxException
from dropbox.files import FileMetadata, ListFolderResult
from pete_e.config.config import settings

# British English comments and docstrings.


class AppleDropboxClient:
    """A robust client for finding and downloading HealthAutoExport files from Dropbox."""

    def __init__(self, request_timeout: float = 30.0):
        """Initialises the client and authenticates with Dropbox."""

        if not all([settings.DROPBOX_APP_KEY, settings.DROPBOX_APP_SECRET, settings.DROPBOX_REFRESH_TOKEN]):
            raise ValueError("Dropbox app key, secret, and refresh token must be set in config.")

        health_path = settings.DROPBOX_HEALTH_METRICS_DIR.strip()
        workouts_path = settings.DROPBOX_WORKOUTS_DIR.strip()

        if not health_path:
            raise ValueError("DROPBOX_HEALTH_METRICS_DIR environment variable is not set.")
        if not workouts_path:
            raise ValueError("DROPBOX_WORKOUTS_DIR environment variable is not set.")

        self.health_metrics_path = health_path if health_path.startswith('/') else f"/{health_path}"
        self.workouts_path = workouts_path if workouts_path.startswith('/') else f"/{workouts_path}"

        self._request_timeout = request_timeout
        self._account_display_name: Optional[str] = None
        # Track Dropbox cursors and the latest modification timestamp we have
        # seen per folder.  This allows incremental listings without re-reading
        # entire directories on subsequent syncs.
        self._folder_cursors: Dict[str, str] = {}
        self._folder_latest_sync: Dict[str, datetime] = {}

        try:
            self.dbx = dropbox.Dropbox(
                app_key=settings.DROPBOX_APP_KEY,
                app_secret=settings.DROPBOX_APP_SECRET,
                oauth2_refresh_token=settings.DROPBOX_REFRESH_TOKEN,
                timeout=self._request_timeout,
            )
            account = self.dbx.users_get_current_account()
            name = getattr(getattr(account, "name", None), "display_name", None)
            if not name:
                name = getattr(account, "email", None)
            self._account_display_name = name
            logging.info("Successfully connected to Dropbox.")
        except AuthError as e:
            logging.error(f"Dropbox authentication failed: {e}")
            raise ValueError("Invalid Dropbox credentials or refresh token.")

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

            # Store the final cursor so that future calls can request only
            # incremental changes.
            self._folder_cursors[folder_path] = result.cursor
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

        all_files: List[FileMetadata]
        cursor = self._folder_cursors.get(folder_path)
        last_sync_time = self._folder_latest_sync.get(folder_path)

        use_incremental = (
            cursor is not None
            and last_sync_time is not None
            and since_datetime >= last_sync_time
        )

        if use_incremental:
            try:
                all_files = []
                result: ListFolderResult = self.dbx.files_list_folder_continue(cursor)
                while True:
                    all_files.extend(
                        entry
                        for entry in result.entries
                        if isinstance(entry, FileMetadata)
                    )
                    if not result.has_more:
                        break
                    result = self.dbx.files_list_folder_continue(result.cursor)

                # Update cursor for subsequent incremental listings.
                self._folder_cursors[folder_path] = result.cursor
            except DropboxException as e:
                logging.warning(
                    "Incremental Dropbox listing for '%s' failed (%s); falling back to full scan.",
                    folder_path,
                    e,
                )
                all_files = self._get_all_files(folder_path)
        else:
            all_files = self._get_all_files(folder_path)

        new_files: List[Tuple[datetime, str]] = []
        latest_seen = since_datetime
        for entry in all_files:
            modified_time = entry.client_modified

            if modified_time.tzinfo is None:
                modified_time = modified_time.replace(tzinfo=timezone.utc)

            if modified_time > latest_seen:
                latest_seen = modified_time

            is_export_file = entry.name.startswith("HealthAutoExport") and entry.name.lower().endswith((".json", ".zip"))

            if is_export_file and modified_time > since_datetime:
                new_files.append((modified_time, entry.path_display))

        # Track the most recent timestamp processed so that subsequent calls can
        # rely on incremental updates.
        self._folder_latest_sync[folder_path] = latest_seen

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
        
    def ping(self) -> str:
        """Returns a brief identifier for the authorised Dropbox account."""
        if self._account_display_name:
            return self._account_display_name
        try:
            account = self.dbx.users_get_current_account()
        except DropboxException as e:
            logging.error(f"Dropbox ping failed: {e}")
            raise IOError(f"Dropbox ping failed: {e}") from e
        name = getattr(getattr(account, "name", None), "display_name", None) or getattr(account, "email", None) or account.account_id
        self._account_display_name = name
        return name

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






