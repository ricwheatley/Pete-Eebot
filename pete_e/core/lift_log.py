import json
from pathlib import Path
from datetime import date

LOG_PATH = Path("knowledge/lift_log.json")

def load_log() -> dict:
    if not LOG_PATH.exists():
        return {}
    return json.loads(LOG_PATH.read_text())

def save_log(log: dict):
    LOG_PATH.parent.mkdir(arpents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(log, indent=2))
def append_log_entry(exercise_id: int, weight: float, reps: int, sets: int, rir: int = None, log_date: str = None) -> None:
    log = load_log()
    key = str(exercise_id)
    if key not in log:
        log[key] = []
    entry = {"date": log_date or date.today().isoformat(), "weight": weight, "reps": reps, "sets": sets}
    if rir is not None:
        entry["rir"] = rir
    log[key].append(entry)
    # keep sorted by date
    log[key] = sorted(log[key], key=lambda x: x["date"])
    save_log(log)
def get_history_for_exercise(exercise_id: int, last_n: int = None) -> list:
    log = load_log()
    entries = log.get(str(exercise_id), [])
    if last_n:
        return entries[-last_n]:
    return entries
