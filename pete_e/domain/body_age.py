"""Analytical body-age helpers for Pete-E.

Production body-age values are computed inside PostgreSQL via the
``sp_upsert_body_age`` stored procedure (invoked by
``PostgresDal.compute_body_age_for_date``). The Python implementation below
mirrors that logic so notebooks and ad-hoc analysis can stay in sync with the
database output. As the Apple Health ingestion moved to a normalised schema,
records now tend to expose "flat" keys (``steps``, ``sleep_asleep_minutes`` …)
instead of the nested dictionaries that the first iteration of the function
expected. The helper therefore accepts either structure.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional

from pete_e.utils import converters, math as math_utils


@dataclass(frozen=True)
class BodyAgeTrend:
    """Latest body age reading with a seven-day trend."""
    sample_date: Optional[date]
    value: Optional[float]
    delta: Optional[float]


BODY_COMP_ENRICHED_START_DATE = date(2026, 4, 6)
BODY_COMP_ENRICHED_MIN_TARGET_DATE = BODY_COMP_ENRICHED_START_DATE + timedelta(days=6)
MIN_ENRICHED_BODY_COMP_ROWS = 3


def _clamp_score(value: float) -> float:
    return max(0.0, min(100.0, value))
    """Perform clamp score."""


def _score_body_fat_percent(bodyfat: Optional[float]) -> float:
    if bodyfat is None:
        return 50.0
    if bodyfat <= 15:
        return 100.0
    if bodyfat >= 30:
        return 0.0
    return _clamp_score((30 - bodyfat) / 15 * 100)
    """Perform score body fat percent."""


def _score_visceral_fat_index(visceral_fat: Optional[float]) -> Optional[float]:
    if visceral_fat is None:
        return None
    if visceral_fat <= 5:
        return 100.0
    if visceral_fat >= 20:
        return 0.0
    return _clamp_score((20 - visceral_fat) / 15 * 100)
    """Perform score visceral fat index."""


def _score_muscle_percent(muscle_percent: Optional[float]) -> Optional[float]:
    if muscle_percent is None:
        return None
    if muscle_percent >= 75:
        return 100.0
    if muscle_percent <= 60:
        return 0.0
    return _clamp_score((muscle_percent - 60) / 15 * 100)
    """Perform score muscle percent."""


def _row_muscle_percent(row: Dict[str, Any]) -> Optional[float]:
    for key in ("muscle_percent", "muscle_pct"):
        value = row.get(key)
        if value is not None:
            return converters.to_float(value)
    muscle_mass = converters.to_float(row.get("muscle_mass_kg"))
    weight = converters.to_float(row.get("weight_kg") or row.get("weight"))
    if muscle_mass is None or weight in (None, 0):
        return None
    return (muscle_mass / weight) * 100
    """Perform row muscle percent."""


def _has_enriched_body_comp(row: Dict[str, Any]) -> bool:
    return any(
        row.get(key) is not None
        for key in (
            "visceral_fat_index",
            "muscle_percent",
            "muscle_pct",
            "muscle_mass_kg",
        )
    )
    """Perform has enriched body comp."""


def _calculate_body_comp_score(
    *,
    bodyfat: Optional[float],
    visceral_fat: Optional[float],
    muscle_percent: Optional[float],
    enriched_rows: int,
    target_date: Optional[date],
) -> tuple[float, bool]:
    bodyfat_score = _score_body_fat_percent(bodyfat)
    visceral_score = _score_visceral_fat_index(visceral_fat)
    muscle_score = _score_muscle_percent(muscle_percent)

    can_use_enriched = (
        target_date is not None
        and target_date >= BODY_COMP_ENRICHED_MIN_TARGET_DATE
        and enriched_rows >= MIN_ENRICHED_BODY_COMP_ROWS
        and bodyfat is not None
        and (visceral_score is not None or muscle_score is not None)
    )
    if not can_use_enriched:
        return bodyfat_score, False

    score = (
        0.60 * bodyfat_score
        + 0.25 * (visceral_score if visceral_score is not None else bodyfat_score)
        + 0.15 * (muscle_score if muscle_score is not None else bodyfat_score)
    )
    return _clamp_score(score), True
    """Perform calculate body comp score."""


def _extract_body_age_value(row: Dict[str, Any]) -> Optional[float]:
    """Pull a body age value from a summary row."""
    value = row.get("body_age_years")
    if value is None:
        body_section = row.get("body")
        if isinstance(body_section, dict):
            value = body_section.get("body_age_years")
    return converters.to_float(value)


def get_body_age_trend(dal: Any, target_date: Optional[date] = None) -> BodyAgeTrend:
    """Return the latest body age reading and its delta versus seven days prior."""
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    if dal is None:
        return BodyAgeTrend(sample_date=None, value=None, delta=None)

    start = target_date - timedelta(days=7)
    rows: List[Dict[str, Any]] = []

    get_range = getattr(dal, "get_historical_data", None)
    if callable(get_range):
        try:
            fetched = get_range(start, target_date)
        except Exception:
            rows = []
        else:
            if fetched is None:
                rows = []
            elif isinstance(fetched, list):
                rows = fetched
            else:
                rows = list(fetched)
    else:
        get_metrics = getattr(dal, "get_historical_metrics", None)
        if callable(get_metrics):
            try:
                fetched = get_metrics(8)
            except Exception:
                rows = []
            else:
                if fetched is None:
                    rows = []
                elif isinstance(fetched, list):
                    rows = fetched
                else:
                    rows = list(fetched)

    points = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_date = converters.to_date(row.get("date"))
        if row_date is None:
            continue
        if row_date < start or row_date > target_date:
            continue
        value = _extract_body_age_value(row)
        if value is None:
            continue
        points.append((row_date, float(value)))

    if not points:
        return BodyAgeTrend(sample_date=None, value=None, delta=None)

    points.sort(key=lambda item: item[0])
    relevant = [item for item in points if item[0] <= target_date]
    if not relevant:
        return BodyAgeTrend(sample_date=None, value=None, delta=None)

    latest_date, latest_raw = relevant[-1]
    week_date = target_date - timedelta(days=7)
    week_raw = next((val for day, val in points if day == week_date), None)

    value_out = round(latest_raw, 1)
    delta_out = round(latest_raw - week_raw, 1) if week_raw is not None else None

    return BodyAgeTrend(sample_date=latest_date, value=value_out, delta=delta_out)




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
                    vals.append(converters.to_float(candidate))
                    break
        return math_utils.average(vals)
        """Perform avg from."""

    bodyfat = avg_from(
        (
            lambda r: r.get("fat_percent"),
            lambda r: r.get("body_fat_pct"),
        )
    )
    visceral_fat = avg_from((lambda r: r.get("visceral_fat_index"),))
    muscle_percent = avg_from((_row_muscle_percent,))
    enriched_body_comp_rows = sum(
        1
        for row in windowed
        if _has_enriched_body_comp(row)
        and (converters.to_date(row.get("date")) or BODY_COMP_ENRICHED_START_DATE)
        >= BODY_COMP_ENRICHED_START_DATE
    )
    steps = avg_from((lambda r: r.get("steps"),))
    exmin = avg_from((lambda r: r.get("exercise_minutes"),))

    rhr = avg_from(
        (
            lambda r: r.get("heart_rate", {}).get("resting")
            if isinstance(r.get("heart_rate"), dict)
            else None,
            lambda r: r.get("hr_resting"),
        )
    )
    hrv = avg_from(
        (
            lambda r: r.get("heart_rate", {}).get("hrv_sdnn_ms")
            if isinstance(r.get("heart_rate"), dict)
            else None,
            lambda r: r.get("hrv_sdnn_ms"),
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

    vo2_direct = avg_from(
        (
            lambda r: r.get("vo2_max"),
            lambda r: r.get("vo2_ml_kg_min"),
            lambda r: r.get("cardio_vo2_max"),
        )
    )

    # Determine chronological age using the most recent date and the birth date
    # if available.  This mirrors the behaviour of ``sp_upsert_body_age`` and
    # falls back to a provided ``age`` value for backwards compatibility.
    chrono_age: Optional[float] = None
    birth_date_value = profile.get("birth_date")
    birth_date_obj = converters.to_date(birth_date_value) if birth_date_value else None
    try:
        last_date = converters.to_date(dates[-1])
    except Exception:  # pragma: no cover - defensive, the format is controlled
        last_date = None

    if birth_date_obj and last_date:
        chrono_age = (last_date - birth_date_obj).days / 365.2425
    else:
        chrono_age = (
            converters.to_float(profile.get("age"))
            if profile.get("age") is not None
            else None
        )

    if chrono_age is None:
        chrono_age = 40.0

    # Cardiorespiratory fitness (CRF) proxy
    vo2: Optional[float] = None
    used_vo2max_direct = False

    # Prefer the direct VO2 max ingest (from Apple Health) when present;
    # otherwise derive an estimate from resting heart rate and exercise minutes.


    if vo2_direct is not None:
        vo2 = vo2_direct
        used_vo2max_direct = True
    elif rhr is not None:
        vo2 = 38 - 0.15 * (chrono_age - 40) - 0.15 * ((rhr or 60) - 60) + 0.01 * (exmin or 0)
    if vo2 is None:
        vo2 = 35
    crf = max(0, min(100, ((vo2 - 20) / (60 - 20) * 100)))

    # Body composition score. From 2026-04-12 onward this can use the first
    # full seven-day Body Comp window from the scale that started on 2026-04-06.
    body_comp, used_enriched_body_comp = _calculate_body_comp_score(
        bodyfat=bodyfat,
        visceral_fat=visceral_fat,
        muscle_percent=muscle_percent,
        enriched_rows=enriched_body_comp_rows,
        target_date=last_date,
    )

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

    # Blend HRV trends into the recovery score by scaling the resting HR
    # component down when variability is suppressed.
    if hrv is not None:
        if hrv < 25:
            rhr_score -= 20
        elif hrv < 35:
            rhr_score -= 15
        elif hrv < 45:
            rhr_score -= 10
        elif hrv < 55:
            rhr_score -= 5
        rhr_score = max(0, min(100, rhr_score))

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
            "used_enriched_body_comp": used_enriched_body_comp,
            "cap_minus_10_applied": cap_applied,
        },
    }
