from datetime import date
from typing import Any, Dict, List

# Import the DataAccessLayer contract, not a specific implementation
from pete_e.data_access.dal import DataAccessLayer


def append_log_entry(
    dal: DataAccessLayer,
    exercise_id: int,
    weight: float,
    reps: int,
    sets: int,
    rir: int | None = None,
    log_date: str | None = None,
) -> None:
    """
    Appends a new entry to the log for a given exercise using the provided DAL.
    """
    # Use the DAL to load the data, instead of reading the file directly
    log = dal.load_lift_log()
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
    
    # Use the DAL to save the data
    dal.save_lift_log(log)


def get_history_for_exercise(
    dal: DataAccessLayer, exercise_id: int, last_n: int | None = None
) -> List[Dict[str, Any]]:
    """
    Retrieves history for an exercise using the provided DAL.
    """
    # Use the DAL to load the data
    log = dal.load_lift_log()
    entries = log.get(str(exercise_id), [])
    
    if last_n:
        return entries[-last_n:]
    return entries

