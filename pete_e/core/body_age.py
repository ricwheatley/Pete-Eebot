"""
Body Age calculation for Pete-E.
"""

from datetime import date
from typing import Any, Dict, List, Optional


def to_float(v: Any) -> Optional[float]:
    """Safely convert a value to float, or return None."""
    try:
        if v in (None, ""):
            return None
        return float(v)
    except Exception:
        return None


def average(values: List[Optional[float]]) -> Optional[float]:
    """Compute the mean of a list, ignoring None values."""
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def calculate_body_age(
    withings_history: List[Dict[str, Any]],
    apple_history: List[Dict[str, Any]],
    profile: Dict[str, Any],
) -> Dict[str, Any]:
    """Compute body age using rolling 7-day averages."""
    today = date.today().isoformat()

    # Collect unique dates from both sources
    dates = sorted({r.get("date") for r in withings_history + apple_history if r.get("date")})
    if not dates:
        return {"date": today, "error": "No input data"}
    dates = dates[-7:]

    # Helper to extract averages from merged records
    def avg_from(fn):
        vals = [to_float(fn(r)) for r in withings_history + apple_history if r.get("date") in dates]
        return average(vals)

    weight = avg_from(lambda r: r.get("weight"))
    bodyfat = avg_from(lambda r: r.get("fat_percent"))
    steps = avg_from(lambda r: r.get("steps"))
    exmin = avg_from(lambda r: r.get("exercise_minutes"))

    c_act = avg_from(lambda r: r.get("calories", {}).get("active") if isinstance(r.get("calories"), dict) else None)
    c_rest = avg_from(lambda r: r.get("calories", {}).get("resting") if isinstance(r.get("calories"), dict) else None)
    c_total = avg_from(lambda r: r.get("calories", {}).get("total") if isinstance(r.get("calories"), dict) else None)

    rhr = avg_from(lambda r: r.get("heart_rate", {}).get("resting") if isinstance(r.get("heart_rate"), dict) else None)
    hravg = avg_from(lambda r: r.get("heart_rate", {}).get("avg") if isinstance(r.get("heart_rate"), dict) else None)

    sleepm = avg_from(lambda r: r.get("sleep", {}).get("asleep") if isinstance(r.get("sleep"), dict) else None)

    chrono_age = profile.get("age", 40)

    # Cardiorespiratory fitness (CRF) proxy
    vo2 = None
    if rhr is not None:
        vo2 = 38 - 0.15 * (chrono_age - 40) - 0.15 * ((rhr or 60) - 60) + 0.01 * (exmin or 0)
    if vo2 is None:
        vo2 = 35
    crf = max(0, min(100, ((vo2 - 20) / (60 - 20) * 100)))

    # Body composition score
    if bodyfat is None:
        body_comp = 50
    elif bodyfat <= 15:
        body_comp = 100
    elif bodyfat >= 30:
        body_comp = 0
    else:
        body_comp = (30 - bodyfat) / (30 - 15) * 100

    # Activity score (weighted between steps and exercise minutes)
    steps_score = 0 if steps is None else max(0, min(100, (steps / 12000) * 100))
    ex_score = 0 if exmin is None else max(0, min(100, (exmin / 30) * 100))
    activity = 0.6 * steps_score + 0.4 * ex_score

    # Recovery score (from sleep and resting HR)
    if sleepm is None:
        sleep_score = 50
    else:
        diff = abs(sleepm - 450)  # 7.5h = 450 minutes
        sleep_score = max(0, min(100, 100 - (diff / 150) * 60))

    if rhr is None:
        rhr_score = 50  # neutral default if missing
    elif rhr <= 55:
        rhr_score = 90
    elif rhr <= 60:
        rhr_score = 80
    elif rhr <= 70:
        rhr_score = 60
    elif rhr <= 80:
        rhr_score = 40
    else:
        rhr_score = 20

    recovery = 0.66 * sleep_score + 0.34 * rhr_score

    # Composite body age score
    composite = 0.40 * crf + 0.25 * body_comp + 0.20 * activity + 0.15 * recovery
    body_age = chrono_age - 0.2 * (composite - 50)

    # Cap improvements to -10 years
    cap_min = chrono_age - 10
    cap_applied = False
    if body_age < cap_min:
        body_age = cap_min
        cap_applied = True

    age_delta = body_age - chrono_age

    return {
        "date": dates[-1],
        "input_window_days": 7,
        "subscores": {
            "crf": round(crf, 1),
            "body_comp": round(body_comp, 1),
            "activity": round(activity, 1),
            "recovery": round(recovery, 1),
        },
        "composite": round(composite, 1),
        "body_age_years": round(body_age, 1),
        "age_delta_years": round(age_delta, 1),
        "assumptions": {
            "used_vo2max_direct": False,
            "cap_minus_10_applied": cap_applied,
        },
    }
