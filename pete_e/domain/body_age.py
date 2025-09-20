# (Functional) Computes “body age” metric from historical data (7-day averages) – currently not wired into main flow (DB procedure is used instead).

"""Body Age calculation for Pete-E.

This module mirrors the PostgreSQL implementation in ``sp_upsert_body_age``.
The database procedure remains the source of truth (it is invoked from the
Postgres DAL), but keeping this Python helper in sync is useful for ad-hoc
analysis or notebooks.  As the Apple Health ingestion moved to a normalised
schema, records now tend to expose "flat" keys (``steps``,
``sleep_asleep_minutes`` …) instead of the nested dictionaries that the first
iteration of the function expected.  The helper therefore accepts either
structure.
"""

from datetime import date, datetime
from typing import Any, Callable, Dict, Iterable, List, Optional


def to_float(v: Any) -> Optional[float]:
    """Safely convert a value to float, or return None."""
    try:
        if v in (None, ""):
            return None
        return float(v)
    except (ValueError, TypeError):
        return None


def average(values: List[Optional[float]]) -> Optional[float]:
    """Compute the mean of a list, ignoring None values."""
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _to_date(value: Any) -> Optional[date]:
    """Best-effort conversion of common date representations to ``date``."""

    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            # ``date.fromisoformat`` cannot parse timestamps; slice the date
            # portion to keep the helper forgiving.
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def calculate_body_age(
    withings_history: List[Dict[str, Any]],
    apple_history: List[Dict[str, Any]],
    profile: Dict[str, Any],
) -> Dict[str, Any]:
    """Compute body age using rolling 7-day averages."""
    today = date.today().isoformat()

    combined: List[Dict[str, Any]] = []
    combined.extend(withings_history)
    combined.extend(apple_history)

    # Collect unique dates from both sources
    dates = sorted({r.get("date") for r in combined if r.get("date")})
    if not dates:
        return {"date": today, "error": "No input data"}
    dates = dates[-7:]

    windowed: List[Dict[str, Any]] = [r for r in combined if r.get("date") in dates]

    def avg_from(accessors: Iterable[Callable[[Dict[str, Any]], Any]]) -> Optional[float]:
        vals: List[Optional[float]] = []
        for row in windowed:
            for accessor in accessors:
                candidate = accessor(row)
                if candidate is not None:
                    vals.append(to_float(candidate))
                    break
        return average(vals)

    weight = avg_from(
        (
            lambda r: r.get("weight"),
            lambda r: r.get("weight_kg"),
        )
    )
    bodyfat = avg_from(
        (
            lambda r: r.get("fat_percent"),
            lambda r: r.get("body_fat_pct"),
        )
    )
    steps = avg_from((lambda r: r.get("steps"),))
    exmin = avg_from((lambda r: r.get("exercise_minutes"),))

    c_act = avg_from(
        (
            lambda r: r.get("calories", {}).get("active")
            if isinstance(r.get("calories"), dict)
            else None,
            lambda r: r.get("calories_active"),
        )
    )
    c_rest = avg_from(
        (
            lambda r: r.get("calories", {}).get("resting")
            if isinstance(r.get("calories"), dict)
            else None,
            lambda r: r.get("calories_resting"),
        )
    )
    c_total = avg_from(
        (
            lambda r: r.get("calories", {}).get("total")
            if isinstance(r.get("calories"), dict)
            else None,
            lambda r: r.get("calories_total"),
        )
    )

    rhr = avg_from(
        (
            lambda r: r.get("heart_rate", {}).get("resting")
            if isinstance(r.get("heart_rate"), dict)
            else None,
            lambda r: r.get("hr_resting"),
        )
    )
    hravg = avg_from(
        (
            lambda r: r.get("heart_rate", {}).get("avg")
            if isinstance(r.get("heart_rate"), dict)
            else None,
            lambda r: r.get("hr_avg"),
        )
    )

    sleepm = avg_from(
        (
            lambda r: r.get("sleep", {}).get("asleep")
            if isinstance(r.get("sleep"), dict)
            else None,
            lambda r: r.get("sleep_asleep_minutes"),
        )
    )

    # Determine chronological age using the most recent date and the birth date
    # if available.  This mirrors the behaviour of ``sp_upsert_body_age`` and
    # falls back to a provided ``age`` value for backwards compatibility.
    chrono_age: Optional[float] = None
    birth_date_value = profile.get("birth_date")
    birth_date_obj = _to_date(birth_date_value) if birth_date_value else None
    try:
        last_date = _to_date(dates[-1])
    except Exception:  # pragma: no cover - defensive, the format is controlled
        last_date = None

    if birth_date_obj and last_date:
        chrono_age = (last_date - birth_date_obj).days / 365.2425
    else:
        chrono_age = to_float(profile.get("age")) if profile.get("age") is not None else None

    if chrono_age is None:
        chrono_age = 40.0

    # Cardiorespiratory fitness (CRF) proxy
    vo2: Optional[float] = None
    used_vo2max_direct = False

    # TODO: if Apple Health provides MetricType "vo2_max", surface the value in
    # ``daily_summary`` (or an adjacent view) so we can consume it here.  When
    # present we should scale the direct VO₂ max reading instead of the proxy
    # formula below and set ``used_vo2max_direct`` accordingly.

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

    # TODO: When Heart Rate Variability (HRV) is available in the aggregated
    # data we can consider blending it into the recovery calculation (e.g. a low
    # HRV could scale down ``rhr_score``).

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
            "used_vo2max_direct": used_vo2max_direct,
            "cap_minus_10_applied": cap_applied,
        },
    }
