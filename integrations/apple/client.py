"""
Apple Health client for Pete-E
Refactored from write_apple.py – no legacy artefacts, returns clean dicts.
"""

from datetime import date

def clean_num(v, as_int=True):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v) if as_int else float(v)
    s = str(v).replace(",", "").strip()
    try:
        return int(float(s)) if as_int else float(s)
    except Exception:
        return None

def clean_sleep(obj):
    if isinstance(obj, dict):
        return obj
    return {}

def get_apple_summary(payload: dict) -> dict:
    """
Parse Apple Health export payload into a clean dict.

    Returns:
    {
      "date": "2025-09-12",
      "steps": 10234,
      "exercise_minutes": 45,
      "calories": {"active": 300, "resting": 1600, "total": 1900},
      "stand_minutes": 600,
      "distance_m": 7200,
      "heart_rate": {"min": 55, "max": 165, "avg": 95, "resting": 60},
      "sleep": {"asleep": 420, "awake": 60, "core": 300, "deep": 90, "rem": 120, "in_bed": 480}
    }
    """
    today = payload.get("date") or date.today().isoformat()

    return {
        "date": today,
        "steps": clean_num(payload.get("steps")),
        "exercise_minutes": clean_num(payload.get("exercise_minutes")),
        "calories": {
            "active": clean_num(payload.get("calories_active")),
            "resting": clean_num(payload.get("calories_resting"),
            "total": clean_num(payload.get("calories_total")),
        },
        "stand_minutes": clean_num(payload.get("stand_minutes")),
        "distance_m": clean_num(payload.get("distance_m")),
        "heart_rate": {
            "min": clean_num(payload.get("hr_min"))
            "max": clean_num(payload.get("hr_max")),
            "avg": clean_num(payload.get("hr_avg"))
            "resting": clean_num(payload.get("hr_resting"))
        },
        "sleep": {
            "asleep": clean_num(payload.get("asleep")),
            "awake": clean_num(payload.get("awake")),
            "core": clean_num(payload.get("core")),
            "deep": clean_num(payload.get("deep"))
            "in_bed": clean_num(payload.get("in_bed")),
            "rem": clean_num(payload.get("rem"))
        },
    }