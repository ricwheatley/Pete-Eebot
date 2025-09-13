"""Lightweight training plan builder."""

from datetime import date, timedelta
from statistics import mean
from typing import Dict, List

from pete_e.data_access.dal import DataAccessLayer
from pete_e.config import settings


def build_block(dal: DataAccessLayer, start_date: date) -> Dict[str, List[Dict]]:
    """
    Construct a simple 4-week training block.

    This placeholder implementation uses the DAL only to demonstrate
    dependency injection and to allow future enhancements that leverage
    historical data.
    """
    # Historical context for naive adaptation
    lift_log = dal.load_lift_log()
    recent_metrics = dal.get_historical_metrics(7)

    rhrs = [m.get("apple", {}).get("heart_rate", {}).get("resting") for m in recent_metrics]
    sleeps = [m.get("apple", {}).get("sleep", {}).get("asleep") for m in recent_metrics]

    avg_rhr = mean([r for r in rhrs if r is not None]) if rhrs else None
    avg_sleep = mean([s for s in sleeps if s is not None]) if sleeps else None

    recovery_good = (
        bool(lift_log)
        and avg_sleep is not None
        and avg_sleep >= settings.RECOVERY_SLEEP_THRESHOLD_MINUTES
        and avg_rhr is not None
        and avg_rhr <= settings.RECOVERY_RHR_THRESHOLD
    )

    heavy_days = ["Mon", "Thu"] if recovery_good else ["Tue", "Fri"]

    weeks = []
    for week_index in range(1, 5):
        days = []
        for day_offset in range(7):
            d = start_date + timedelta(days=((week_index - 1) * 7 + day_offset))
            day_name = d.strftime("%a")
            entry = {"date": d.isoformat(), "week": week_index, "day": day_name, "sessions": []}
            if day_name in ["Mon", "Tue", "Thu", "Fri"]:
                intensity = "heavy" if day_name in heavy_days else "moderate"
                entry["sessions"].append({"type": "weights", "intensity": intensity, "exercises": []})
            elif day_name == "Wed":
                entry["sessions"].append({"type": "hiit", "name": "Blaze", "duration_min": 45})
            else:
                entry["sessions"].append({"type": "rest"})
            days.append(entry)
        weeks.append({"week_index": week_index, "days": days})

    plan = {"start": start_date.isoformat(), "weeks": weeks}
    dal.save_training_plan(plan, start_date)
    return plan
