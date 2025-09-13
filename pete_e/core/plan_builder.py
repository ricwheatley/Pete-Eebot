"""Lightweight training plan builder."""

from datetime import date, timedelta
from typing import Dict, List

from pete_e.data_access.dal import DataAccessLayer


def build_block(dal: DataAccessLayer, start_date: date) -> Dict[str, List[Dict]]:
    """
    Construct a simple 4-week training block.

    This placeholder implementation uses the DAL only to demonstrate
    dependency injection and to allow future enhancements that leverage
    historical data.
    """
    # Fetch history (not yet used but proves DAL integration)
    _ = dal.load_history()

    weeks = []
    for week_index in range(1, 5):
        days = []
        for day_offset in range(7):
            d = start_date + timedelta(days=((week_index - 1) * 7 + day_offset))
            day_name = d.strftime("%a")
            entry = {"date": d.isoformat(), "week": week_index, "day": day_name, "sessions": []}
            if day_name in ["Mon", "Tue", "Thu", "Fri"]:
                entry["sessions"].append({"type": "weights", "exercises": []})
            elif day_name == "Wed":
                entry["sessions"].append({"type": "hiit", "name": "Blaze", "duration_min": 45})
            else:
                entry["sessions"].append({"type": "rest"})
            days.append(entry)
        weeks.append({"week_index": week_index, "days": days})

    return {"start": start_date.isoformat(), "weeks": weeks}
