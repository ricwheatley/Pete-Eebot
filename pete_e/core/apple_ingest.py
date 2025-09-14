import json
import sys
from pathlib import Path
from datetime import date

from pete_e.core import apple_client
from pete_e.core.sync import _get_dal
from pete_e.infra import log_utils

def ingest_file(path: Path):
    dal = _get_dal()
    data = json.loads(path.read_text())
    summary = apple_client.get_apple_summary(data)
    day = summary.get("date") or date.today().isoformat()
    dal.save_daily_summary({"apple": summary, "withings": {}, "wger": {}}, date.fromisoformat(day))
    log_utils.log_message(f"Ingested Apple file {path.name} for {day}", "INFO")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m pete_e.core.apple_ingest <file.json>")
        sys.exit(1)
    ingest_file(Path(sys.argv[1]))
