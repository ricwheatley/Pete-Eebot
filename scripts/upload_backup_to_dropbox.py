#!/usr/bin/env python3
"""Upload encrypted backup artifacts to Dropbox."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import dropbox
from dropbox.exceptions import ApiError
from dropbox.files import CommitInfo, UploadSessionCursor, WriteMode
from dotenv import load_dotenv

CHUNK_SIZE = 8 * 1024 * 1024
SMALL_UPLOAD_LIMIT = 150 * 1024 * 1024


def find_env_path() -> Path:
    script_path = Path(__file__).resolve()
    for directory in (script_path.parent, *script_path.parents):
        env_path = directory / ".env"
        if env_path.exists():
            return env_path
    raise FileNotFoundError("No .env file found beside the script or its parent directories.")


def dropbox_join(base_dir: str, filename: str) -> str:
    base = "/" + base_dir.strip("/")
    return f"{base}/{filename}" if base != "/" else f"/{filename}"


def latest_filename(filename: str) -> str:
    match = re.match(r"^(postgres|env|withings_tokens)_\d{8}T\d{6}Z\.enc$", filename)
    if not match:
        return filename
    return f"{match.group(1)}_latest.enc"


def ensure_dropbox_folder(dbx: dropbox.Dropbox, folder_path: str) -> None:
    folder = "/" + folder_path.strip("/")
    if folder == "/":
        return

    current = ""
    for part in folder.strip("/").split("/"):
        current = f"{current}/{part}"
        try:
            dbx.files_create_folder_v2(current)
        except ApiError as exc:
            if not exc.error.is_path() or not exc.error.get_path().is_conflict():
                raise


def upload_file(dbx: dropbox.Dropbox, local_path: Path, dropbox_path: str) -> None:
    size = local_path.stat().st_size
    with local_path.open("rb") as handle:
        if size <= SMALL_UPLOAD_LIMIT:
            dbx.files_upload(
                handle.read(),
                dropbox_path,
                mode=WriteMode("overwrite"),
                mute=True,
            )
            return

        session = dbx.files_upload_session_start(handle.read(CHUNK_SIZE))
        cursor = UploadSessionCursor(session_id=session.session_id, offset=handle.tell())
        commit = CommitInfo(path=dropbox_path, mode=WriteMode("overwrite"), mute=True)

        while handle.tell() < size:
            remaining = size - handle.tell()
            if remaining <= CHUNK_SIZE:
                dbx.files_upload_session_finish(handle.read(CHUNK_SIZE), cursor, commit)
            else:
                dbx.files_upload_session_append_v2(handle.read(CHUNK_SIZE), cursor)
                cursor.offset = handle.tell()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Upload backup files to Dropbox.")
    parser.add_argument("--target-dir", required=True, help="Timestamped Dropbox backup folder.")
    parser.add_argument("--latest-dir", help="Dropbox folder to overwrite with the latest backup files.")
    parser.add_argument("files", nargs="+", type=Path, help="Local encrypted files to upload.")
    args = parser.parse_args(argv)

    load_dotenv(dotenv_path=find_env_path())

    required = ["DROPBOX_APP_KEY", "DROPBOX_APP_SECRET", "DROPBOX_REFRESH_TOKEN"]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        print(f"ERROR: Missing Dropbox environment values: {', '.join(missing)}", file=sys.stderr)
        return 1

    dbx = dropbox.Dropbox(
        app_key=os.environ["DROPBOX_APP_KEY"],
        app_secret=os.environ["DROPBOX_APP_SECRET"],
        oauth2_refresh_token=os.environ["DROPBOX_REFRESH_TOKEN"],
        timeout=float(os.environ.get("DROPBOX_BACKUP_TIMEOUT", "60")),
    )

    ensure_dropbox_folder(dbx, args.target_dir)
    if args.latest_dir:
        ensure_dropbox_folder(dbx, args.latest_dir)

    for local_path in args.files:
        if not local_path.is_file():
            print(f"ERROR: Backup artifact not found: {local_path}", file=sys.stderr)
            return 1

        upload_file(dbx, local_path, dropbox_join(args.target_dir, local_path.name))
        print(f"Uploaded {local_path} to {args.target_dir}.")

        if args.latest_dir:
            upload_file(dbx, local_path, dropbox_join(args.latest_dir, latest_filename(local_path.name)))
            print(f"Uploaded {local_path} to {args.latest_dir}.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
