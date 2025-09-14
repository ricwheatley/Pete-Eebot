import subprocess
import shutil
from pathlib import Path
from datetime import date

from pete_e.core import apple_client
from pete_e.core.sync import _get_dal
from pete_e.infra import log_utils
import json

DOWNLOADS = Path.home() / "Downloads"
INCOMING = Path.home() / "pete-eebot" / "apple-incoming"

def fetch_files():
    # clear Downloads into incoming before getting new
    for f in DOWNLOADS.glob("apple_*.*"):
        shutil.move(str(f), INCOMING / f.name)
    subprocess.run(["tailscale", "file", "get", str(DOWNLOADS)], check=False)

def ingest_file(path: Path):
    dal = _get_dal()
    try:
        data = json.loads(path.read_text())
        summary = apple_client.get_apple_summary(data)
        day = summary.get("date") or date.today().isoformat()
        dal.save_daily_summary({"apple": summary, "withings": {}, "wger": {}}, date.fromisoformat(day))
        log_utils.log_message(f"Ingested Apple file {path.name} for {day}", "INFO")
    except Exception as e:
        log_utils.log_message(f"Failed to ingest {path.name}: {e}", "ERROR")

def process_downloads():
    for file in DOWNLOADS.glob("apple_*.*"):
        dest = INCOMING / file.name
        try:
            shutil.move(str(file), dest)
            ingest_file(dest)
            dest.unlink()  # delete after ingest
        except Exception as e:
            log_utils.log_message(f"Error processing {file.name}: {e}", "ERROR")

if __name__ == "__main__":
    INCOMING.mkdir(parents=True, exist_ok=True)
    fetch_files()
    process_downloads()
