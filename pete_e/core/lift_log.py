import json
from pathlib import Path
from datetime import date
from typing import Dict, List, Any

LOG_PATH = Path("knowledge/lift_log.json")


def load_log() -> Dict[str, Any]:
    """Load the lift log JSON file, or return an empty dict if missing."""
    if not LOG_PATH.exists():
        return {}
    return json.loads(LOG_PATH.read_text(encoding="utf-8"))


def save_log(log: Dict[str, Any]) -> None:
    """Save the lift log to disk in JSON format."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(log, indent=2), encoding="utf-8")


def append_log_entry(
    exercise_id: int,
    weight: float,
    reps: int,
    sets: int,
    rir: int | None = None,
    log_date: str | None = None,
) -> None:
    """Append a new entry to the log for a given exercise."""
    log = load_log()
    key = str(exercise_id)
    if key not in log:
        log[key] = []

    entry = {
        "date": log_date or date.today().isoformat(),
        "weight": weight,
        "reps": reps,
        "sets": sets,
    }
    if rir is not None:
        entry["rir"] = rir

    log[key].append(entry)

    # Keep sorted by date
    log[key] = sorted(log[key], key=lambda x: x["date"])
    save_log(log)


def get_history_for_exercise(exercise_id: int, last_n: int | None = None) -> List[Dict[str, Any]]:
    """Retrieve history for a given exercise, optionally limited to the last N entries."""
    log = load_log()
    entries = log.get(str(exercise_id), [])
    if last_n:
        return entries[-last_n:]
    return entries
