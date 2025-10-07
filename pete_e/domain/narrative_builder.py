# (Functional) Builds daily/weekly/cycle summaries using domain metrics and phrases. *(Uses `phrase_picker` and `narrative_utils` to generate chatty text.)*

import random
from dataclasses import dataclass, field
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from pete_e.domain.phrase_picker import random_phrase as phrase_for
from pete_e.domain import narrative_utils
from pete_e.config import settings
from pete_e.infrastructure.log_utils import log_message
from pete_e.utils import converters, formatters, helpers


_DAY_NAMES = {
    1: "Monday",
    2: "Tuesday",
    3: "Wednesday",
    4: "Thursday",
    5: "Friday",
    6: "Saturday",
    7: "Sunday",
}


_COACH_GREETINGS = [
    "Yo Ric! Coach Pete sliding into your DMs 💥",
    "Oi Ric! Your coach-on-call is buzzing your phone 📲",
    "Morning Ric! Clipboard in one hand, hype in the other ☕️",
]

_COACH_WEEKLY_GREETINGS = [
    "Yo Ric! Coach Pete's weekly huddle incoming 📅",
    "Oi Ric! Fresh plan drop-off straight from the war room 📓",
    "Coach Pete here – plotting your next week's domination 🧠",
]

_DAILY_HEADINGS = [
    "*{weekday} {day} {month}: Daily Flex*",
    "*{weekday} {day} {month}: Momentum Check*",
]

_WEEKLY_HEADINGS = [
    "*Week {week} Game Plan · {start} → {end}*",
    "*Week {week} Battle Plan · {start} → {end}*",
]

@dataclass
class CoachMessage:
    greeting: str
    heading: str
    bullets: List[str] = field(default_factory=list)
    narrative: List[str] = field(default_factory=list)
    closers: List[str] = field(default_factory=list)

    def render(self) -> str:
        lines: List[str] = []
        greeting = (self.greeting or "").strip()
        heading = (self.heading or "").strip()
        if greeting:
            lines.append(greeting)
        if heading:
            if lines:
                lines.append("")
            lines.append(heading)
        for block in (self.bullets, self.narrative, self.closers):
            for line in block:
                if not line:
                    continue
                stripped = str(line).strip()
                if stripped:
                    lines.append(stripped)
        return "\n".join(lines).strip()

def _safe_phrase(tags: List[str], fallback: str) -> str:
    try:
        phrase = phrase_for(tags=tags)
    except Exception as exc:  # pragma: no cover - defensive logging
        log_message(f"Phrase lookup failed for {tags}: {exc}", "WARN")
        phrase = None
    text = (phrase or "").strip()
    if not text or "no phrases available" in text.lower():
        text = (fallback or "").strip()
    return text or fallback

def _closing_phrases(
    primary_tags: List[str],
    fallback: str,
    *,
    secondary_tags: List[str] | None = None,
    secondary_fallback: str = "Keep recovery playful and snappy.",
) -> List[str]:
    closers: List[str] = []
    primary = _safe_phrase(primary_tags, fallback)
    if primary:
        closers.append(primary)
    if secondary_tags and random.random() > 0.65:
        secondary = _safe_phrase(secondary_tags, secondary_fallback)
        if secondary:
            closers.append(secondary)
    return closers

@dataclass(frozen=True)
class _TrendMetric:
    name: str
    paths: Tuple[Tuple[str, ...], ...]
    format_value: Callable[[float], str]
    format_delta: Callable[[float], str]
    significance: float
    min_week_samples: int = 4
    min_month_samples: int = 20
    min_baseline_samples: int = 21
    include_zero: bool = False


def _trend_steps_value(value: float) -> str:
    return f"{value:,.0f} steps/day"


def _trend_steps_delta(value: float) -> str:
    return f"{value:,.0f} steps"


def _trend_sleep_value(value: float) -> str:
    hours = value / 60.0
    return f"{hours:.1f} h/night"


def _trend_sleep_delta(value: float) -> str:
    hours = value / 60.0
    return f"{hours:.1f} h"


_TREND_METRICS: Tuple[_TrendMetric, ...] = (
    _TrendMetric(
        name="Steps",
        paths=(("activity", "steps"), ("steps",)),
        format_value=_trend_steps_value,
        format_delta=_trend_steps_delta,
        significance=400.0,
    ),
    _TrendMetric(
        name="Sleep",
        paths=(("sleep", "asleep_minutes"), ("sleep_asleep_minutes",)),
        format_value=_trend_sleep_value,
        format_delta=_trend_sleep_delta,
        significance=6.0,
    ),
)


def _resolve_metric_value(payload: Mapping[str, Any], metric: _TrendMetric) -> float | None:
    for path in metric.paths:
        current: Any = payload
        for key in path:
            if not isinstance(current, Mapping):
                current = None
                break
            current = current.get(key)
        if current is None:
            continue
        value = _to_float(current)
        if value is None:
            continue
        if value <= 0 and not metric.include_zero:
            continue
        return value
    return None


def _collect_trend_series(
    metric: _TrendMetric,
    samples: Sequence[tuple[date | datetime, Mapping[str, Any]]],
) -> List[tuple[date, float]]:
    collected: List[tuple[date, float]] = []
    for sample_date, payload in samples:
        day = sample_date
        if isinstance(day, datetime):
            day = day.date()
        elif not isinstance(day, date):
            day = converters.to_date(day)
        if not isinstance(day, date):
            continue
        if not isinstance(payload, Mapping):
            continue
        value = _resolve_metric_value(payload, metric)
        if value is None:
            continue
        collected.append((day, float(value)))
    collected.sort(key=lambda item: item[0])
    return collected


def _mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _build_trend_line(
    metric: _TrendMetric,
    samples: Sequence[tuple[date | datetime, Mapping[str, Any]]],
    target_day: date,
) -> str:
    series = _collect_trend_series(metric, samples)
    if not series:
        return f"{metric.name} trend: no data logged yet."
    filtered = [(day, value) for day, value in series if day <= target_day]
    if not filtered:
        return f"{metric.name} trend: no data logged yet."

    week_start = target_day - timedelta(days=6)
    month_start = target_day - timedelta(days=29)
    baseline_start = target_day - timedelta(days=89)
    baseline_end = month_start - timedelta(days=1)

    week_values = [value for day, value in filtered if week_start <= day <= target_day]
    month_values = [value for day, value in filtered if month_start <= day <= target_day]
    baseline_values = [value for day, value in filtered if baseline_start <= day <= baseline_end]

    if len(week_values) < metric.min_week_samples or len(month_values) < metric.min_month_samples:
        logged_days = len(month_values) or len(filtered)
        return f"{metric.name} trend: need more data logged (only {logged_days} days in last 30d)."

    week_avg = _mean(week_values)
    month_avg = _mean(month_values)
    if week_avg is None or month_avg is None:
        return f"{metric.name} trend: need more data logged."

    delta = week_avg - month_avg
    month_text = metric.format_value(month_avg)
    if abs(delta) >= metric.significance:
        direction = "up" if delta > 0 else "down"
        delta_text = f"{direction} {metric.format_delta(abs(delta))} vs 30d avg {month_text}"
    else:
        delta_text = f"steady vs 30d avg {month_text}"

    if len(baseline_values) >= metric.min_baseline_samples:
        baseline_avg = _mean(baseline_values)
    else:
        baseline_avg = None

    if baseline_avg is None:
        baseline_clause = "60d base still forming"
    else:
        baseline_delta = month_avg - baseline_avg
        baseline_diff = abs(baseline_delta) if baseline_delta is not None else None
        if baseline_diff is not None and baseline_diff >= (metric.significance / 2):
            baseline_direction = "up" if baseline_delta > 0 else "down"
            baseline_clause = (
                f"{baseline_direction} {metric.format_delta(baseline_diff)} vs 60d base "
                f"{metric.format_value(baseline_avg)}"
            )
        else:
            baseline_clause = f"60d base {metric.format_value(baseline_avg)}"

    week_text = metric.format_value(week_avg)
    return f"{metric.name} trend: {week_text} ({delta_text}; {baseline_clause})."


def compute_trend_lines(
    samples: Sequence[tuple[date | datetime, Mapping[str, Any]]],
    *,
    as_of: date | None = None,
    limit: int | None = None,
) -> List[str]:
    if not samples:
        return []

    normalized: List[tuple[date, Mapping[str, Any]]] = []
    for sample_date, payload in samples:
        day = sample_date
        if isinstance(day, datetime):
            day = day.date()
        elif not isinstance(day, date):
            day = converters.to_date(day)
        if not isinstance(day, date):
            continue
        if not isinstance(payload, Mapping):
            continue
        normalized.append((day, payload))

    if not normalized:
        return []

    normalized.sort(key=lambda item: item[0])
    target_day = as_of or normalized[-1][0]

    lines: List[str] = []
    for metric in _TREND_METRICS:
        line = _build_trend_line(metric, normalized, target_day)
        if line:
            lines.append(formatters.ensure_sentence(line))

    if limit is not None:
        lines = lines[:limit]
    return lines


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def _to_int(value: Any) -> int | None:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None

def _format_daily_heading(day_value: date | None) -> str:
    if day_value is None:
        return "*Daily Flex*"
    template = helpers.choose_from(_DAILY_HEADINGS, "*{weekday} {day} {month}: Daily Flex*")
    context = {
        "weekday": day_value.strftime("%A"),
        "day": day_value.strftime("%d"),
        "month": day_value.strftime("%b"),
    }
    return template.format(**context)

def _format_weight(value: Any) -> str | None:
    val = _to_float(value)
    if val is None:
        return None
    return f"Weight: {val:.1f} kg"

def _format_body_fat(value: Any) -> str | None:
    val = _to_float(value)
    if val is None:
        return None
    return f"Body fat: {val:.1f}%"

def _format_muscle_pct(value: Any) -> str | None:
    val = _to_float(value)
    if val is None:
        return None
    return f"Muscle: {val:.1f}%"


def _format_water_pct(value: Any) -> str | None:
    val = _to_float(value)
    if val is None:
        return None
    return f"Hydration: {val:.1f}%"

def _format_resting_hr(value: Any) -> str | None:
    val = _to_int(value)
    if val is None:
        return None
    return f"Resting HR: {val} bpm"

def _format_hrv(value: Any) -> str | None:
    val = _to_float(value)
    if val is None or val <= 0:
        return None
    return f"HRV: {val:.0f} ms"

def _format_steps(value: Any) -> str | None:
    val = _to_int(value)
    if val is None or val <= 0:
        return None
    return f"Steps: {val:,} struts"

def _format_active_calories(value: Any) -> str | None:
    val = _to_int(value)
    if val is None or val < 0:
        return None
    return f"Active burn: {val:,} kcal"


def _format_resting_calories(value: Any) -> str | None:
    val = _to_int(value)
    if val is None or val < 0:
        return None
    return f"Resting burn: {val:,} kcal"


def _format_distance(value: Any) -> str | None:
    dist = _to_float(value)
    if dist is None or dist <= 0:
        return None
    if dist >= 1000:
        km = dist / 1000.0
        return f"Distance: {_clean_number(round(km, 2))} km covered"
    return f"Distance: {_clean_number(round(dist))} m covered"


def _format_flights(value: Any) -> str | None:
    val = _to_int(value)
    if val is None or val <= 0:
        return None
    return f"Flights climbed: {val}"


def _format_exercise_minutes(value: Any) -> str | None:
    val = _to_int(value)
    if val is None or val <= 0:
        return None
    return f"Exercise: {val} min logged"


def _format_stand_minutes(value: Any) -> str | None:
    val = _to_int(value)
    if val is None or val <= 0:
        return None
    return f"Stand: {val} min upright"


def _format_daylight_minutes(value: Any) -> str | None:
    val = _to_int(value)
    if val is None or val <= 0:
        return None
    return f"Daylight: {val} min outside"


def _format_strength_volume(value: Any) -> str | None:
    val = _to_float(value)
    if val is None or val <= 0:
        return None
    return f"Strength volume: {val:,.0f} kg moved"


def _format_hr_avg(value: Any) -> str | None:
    val = _to_int(value)
    if val is None or val <= 0:
        return None
    return f"Avg HR: {val} bpm"


def _format_hr_max(value: Any) -> str | None:
    val = _to_int(value)
    if val is None or val <= 0:
        return None
    return f"Max HR: {val} bpm"


def _format_hr_min(value: Any) -> str | None:
    val = _to_int(value)
    if val is None or val <= 0:
        return None
    return f"Min HR: {val} bpm"


def _format_walking_hr_avg(value: Any) -> str | None:
    val = _to_int(value)
    if val is None or val <= 0:
        return None
    return f"Walking HR avg: {val} bpm"


def _format_cardio_recovery(value: Any) -> str | None:
    val = _to_float(value)
    if val is None or val <= 0:
        return None
    return f"Cardio recovery: {val:.1f} bpm"


def _format_respiratory_rate(value: Any) -> str | None:
    val = _to_float(value)
    if val is None or val <= 0:
        return None
    return f"Respiratory rate: {val:.1f} breaths/min"


def _format_blood_oxygen(value: Any) -> str | None:
    val = _to_float(value)
    if val is None or val <= 0:
        return None
    return f"SpO2: {val:.1f}%"


def _format_wrist_temperature(value: Any) -> str | None:
    val = _to_float(value)
    if val is None:
        return None
    return f"Wrist temp: {val:.1f} degC"


def _format_vo2_max(value: Any) -> str | None:
    val = _to_float(value)
    if val is None or val <= 0:
        return None
    return f"VO2max: {val:.1f} ml/kg/min"


def _format_body_age_years(value: Any) -> str | None:
    val = _to_float(value)
    if val is None or val <= 0:
        return None
    return f"Body age: {val:.1f} yr"


def _format_body_age_delta(value: Any) -> str | None:
    val = _to_float(value)
    if val is None:
        return None
    return f"Body age delta: {val:+.1f} yr"


def _format_minutes_duration(value: Any, label: str, *, suffix: str | None = None) -> str | None:
    total = _to_int(value)
    if total is None or total <= 0:
        return None
    hours, minutes = divmod(total, 60)
    parts: List[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append("0m")
    text = f"{label}: {' '.join(parts)}"
    if suffix:
        text = f"{text} {suffix}"
    return text


def _format_sleep_total_minutes(value: Any) -> str | None:
    return _format_minutes_duration(value, "Sleep total")


def _format_sleep_minutes(value: Any) -> str | None:
    return _format_minutes_duration(value, "Sleep", suffix="logged")


def _format_sleep_rem_minutes(value: Any) -> str | None:
    return _format_minutes_duration(value, "REM sleep")


def _format_sleep_deep_minutes(value: Any) -> str | None:
    return _format_minutes_duration(value, "Deep sleep")


def _format_sleep_core_minutes(value: Any) -> str | None:
    return _format_minutes_duration(value, "Core sleep")


def _format_sleep_awake_minutes(value: Any) -> str | None:
    return _format_minutes_duration(value, "Awake")


_DAILY_METRIC_BUILDERS = {
    "weight_kg": _format_weight,
    "body_fat_pct": _format_body_fat,
    "muscle_pct": _format_muscle_pct,
    "water_pct": _format_water_pct,
    "body_age_years": _format_body_age_years,
    "body_age_delta_years": _format_body_age_delta,
    "hr_resting": _format_resting_hr,
    "hr_avg": _format_hr_avg,
    "hr_max": _format_hr_max,
    "hr_min": _format_hr_min,
    "walking_hr_avg": _format_walking_hr_avg,
    "cardio_recovery": _format_cardio_recovery,
    "respiratory_rate": _format_respiratory_rate,
    "blood_oxygen_saturation": _format_blood_oxygen,
    "wrist_temperature": _format_wrist_temperature,
    "hrv_sdnn_ms": _format_hrv,
    "vo2_max": _format_vo2_max,
    "steps": _format_steps,
    "distance_m": _format_distance,
    "flights_climbed": _format_flights,
    "exercise_minutes": _format_exercise_minutes,
    "calories_active": _format_active_calories,
    "calories_resting": _format_resting_calories,
    "stand_minutes": _format_stand_minutes,
    "time_in_daylight": _format_daylight_minutes,
    "strength_volume_kg": _format_strength_volume,
    "sleep_total_minutes": _format_sleep_total_minutes,
    "sleep_asleep_minutes": _format_sleep_minutes,
    "sleep_rem_minutes": _format_sleep_rem_minutes,
    "sleep_deep_minutes": _format_sleep_deep_minutes,
    "sleep_core_minutes": _format_sleep_core_minutes,
    "sleep_awake_minutes": _format_sleep_awake_minutes,
}

_DAILY_METRIC_ORDER = [
    "weight_kg",
    "body_fat_pct",
    "muscle_pct",
    "water_pct",
    "body_age_years",
    "body_age_delta_years",
    "hr_resting",
    "hr_avg",
    "hr_max",
    "hr_min",
    "walking_hr_avg",
    "cardio_recovery",
    "respiratory_rate",
    "blood_oxygen_saturation",
    "wrist_temperature",
    "hrv_sdnn_ms",
    "vo2_max",
    "steps",
    "distance_m",
    "flights_climbed",
    "exercise_minutes",
    "calories_active",
    "calories_resting",
    "stand_minutes",
    "time_in_daylight",
    "strength_volume_kg",
    "sleep_total_minutes",
    "sleep_asleep_minutes",
    "sleep_rem_minutes",
    "sleep_deep_minutes",
    "sleep_core_minutes",
    "sleep_awake_minutes",
]


def _format_readiness_line(summary_data: Dict[str, Any]) -> str | None:
    headline = summary_data.get("readiness_headline") or summary_data.get("readiness_state")
    tip = summary_data.get("readiness_tip")
    if not headline and not tip:
        return None
    if headline and tip:
        return formatters.ensure_sentence(f"Coach's call: {headline} - {tip}")
    if headline:
        return formatters.ensure_sentence(f"Coach's call: {headline}")
    if tip:
        return formatters.ensure_sentence(f"Coach's call: {tip}")
    return None


def _format_environment_line(summary_data: Dict[str, Any]) -> str | None:
    temp = _to_float(summary_data.get("environment_temp_degc"))
    humidity = _to_float(summary_data.get("environment_humidity_percent"))
    if temp is None and humidity is None:
        return None

    parts: List[str] = []
    if temp is not None:
        temp_value = round(temp, 1)
        parts.append(f"{_clean_number(temp_value)} degC")
    if humidity is not None:
        humidity_value = humidity
        if humidity_value <= 1.0:
            humidity_value = humidity_value * 100.0
        humidity_value = max(0.0, min(100.0, humidity_value))
        parts.append(f"{_clean_number(round(humidity_value))}% humidity")

    if not parts:
        return None

    values_text = parts[0] if len(parts) == 1 else " and ".join(parts)
    return f"Environment: {values_text} reported for the workout."


def _no_daily_metrics_message() -> str:
    message = CoachMessage(
        greeting=helpers.choose_from(_COACH_GREETINGS, "Coach Pete checking in"),
        heading="*Daily Flex*",
        bullets=["- No fresh metrics landed – give your trackers a sync and shout me once it's in."],
        closers=_closing_phrases(["#Consistency"], "Consistency is queen, volume is king!"),
    )
    return message.render()

def _clean_number(raw: Any) -> str:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return str(raw)
    if value.is_integer():
        return str(int(value))
    return f"{value:g}"

def _format_weekly_heading(week_number: int, week_start: date | None) -> str:
    if week_start is None:
        return f"*Week {week_number} Game Plan*"
    template = helpers.choose_from(_WEEKLY_HEADINGS, "*Week {week} Game Plan · {start} → {end}*")
    week_end = week_start + timedelta(days=6)
    return template.format(
        week=week_number,
        start=week_start.isoformat(),
        end=week_end.isoformat(),
    )

def _format_weekly_workouts(plan_week_data: List[Dict[str, Any]]) -> tuple[List[str], List[str]]:
    workouts_by_day: Dict[int, List[str]] = {day: [] for day in range(1, 8)}
    for entry in plan_week_data:
        day_value = entry.get("day_of_week")
        try:
            day_number = int(day_value)
        except (TypeError, ValueError):
            continue
        if day_number not in workouts_by_day:
            continue
        exercise = entry.get("exercise_name") or f"Exercise {entry.get('exercise_id')}"
        details: List[str] = []
        sets = entry.get("sets")
        reps = entry.get("reps")
        if sets is not None and reps is not None:
            details.append(f"{_clean_number(sets)} x {_clean_number(reps)}")
        weight = entry.get("target_weight_kg") or entry.get("weight_kg")
        if weight is not None:
            details.append(f"{_clean_number(weight)} kg")
        rir = entry.get("rir")
        if rir is not None:
            details.append(f"RIR {_clean_number(rir)}")
        detail_text = f" ({' · '.join(details)})" if details else ""
        workouts_by_day[day_number].append(f"{exercise}{detail_text}")
    bullet_lines: List[str] = []
    rest_days: List[str] = []
    for day_number in range(1, 8):
        label = _DAY_NAMES.get(day_number, f"Day {day_number}")
        entries = workouts_by_day.get(day_number, [])
        if entries:
            bullet_lines.append(f"- {label}: {' | '.join(entries)}")
        else:
            rest_days.append(label)
    return bullet_lines, rest_days

def _format_rest_line(rest_days: List[str]) -> str | None:
    if not rest_days:
        return None
    if len(rest_days) == 1:
        days_text = rest_days[0]
    elif len(rest_days) == 2:
        days_text = " & ".join(rest_days)
    else:
        days_text = ", ".join(rest_days[:-1]) + f", {rest_days[-1]}"
    return f"- Rest windows: {days_text} - keep them mobile."

def _no_plan_message(week_number: int) -> str:
    message = CoachMessage(
        greeting=helpers.choose_from(_COACH_WEEKLY_GREETINGS, "Coach Pete here"),
        heading=f"*Week {week_number} Game Plan*",
        bullets=["- I couldn't find workouts for this week – ping me once the plan's loaded."],
        closers=_closing_phrases(["#Motivation"], "We'll build the week the moment data lands."),
    )
    return message.render()

def compare_text(current, previous, unit: str = "", context: str = "") -> str:
    """Return chatty comparative text instead of robotic % changes."""
    if previous is None or previous == 0:
        return f"{current}{unit} {context}".strip()

    diff = current - previous
    pct = (diff / previous) * 100

    if abs(pct) < 5:
        return f"{current}{unit} {context}, about the same as before".strip()
    elif pct > 0:
        return f"{current}{unit} {context}, up a bit from {previous}{unit}".strip()
    else:
        return f"{current}{unit} {context}, down a bit from {previous}{unit}".strip()


# -------------------------------------------------------------------------
# Daily / Weekly / Cycle summaries
# -------------------------------------------------------------------------

def build_daily_narrative(metrics: Dict[str, Any]) -> str:
    days = metrics.get("days", {})
    if not days:
        return "Morning mate 👋\n\nNo logs found for yesterday. Did you rest? 😴"

    all_dates = sorted(days.keys())
    yesterday = all_dates[-1]
    today_data = days[yesterday]
    prev_data = days.get(all_dates[-2]) if len(all_dates) > 1 else {}

    greeting = random.choice([
        "Morning mate 👋",
        "Morning Ric 🌞",
        "Hey Ric, ready for today?"
    ])

    insights: List[str] = []

    # Strength
    if "strength" in today_data:
        total_vol = sum(ex["volume_kg"] for ex in today_data["strength"])
        prev_vol = sum(ex["volume_kg"] for ex in prev_data.get("strength", [])) if prev_data else None
        insights.append(f"You lifted {compare_text(int(total_vol), int(prev_vol) if prev_vol else None, 'kg')}.")

    # Steps
    steps = today_data.get("activity", {}).get("steps")
    prev_steps = prev_data.get("activity", {}).get("steps") if prev_data else None
    if steps:
        insights.append(f"You did {compare_text(int(steps), prev_steps, 'steps', 'yesterday')}.")

    # Sleep
    sleep = today_data.get("sleep", {}).get("asleep_minutes")
    prev_sleep = prev_data.get("sleep", {}).get("asleep_minutes") if prev_data else None
    if sleep:
        hrs = round(sleep / 60)
        prev_hrs = round(prev_sleep / 60) if prev_sleep else None
        insights.append(f"You slept {compare_text(hrs, prev_hrs, 'h')}.")

    # Weight
    weight = today_data.get("body", {}).get("weight_kg")
    prev_weight = prev_data.get("body", {}).get("weight_kg") if prev_data else None
    if weight:
        insights.append(f"Weight came in at {compare_text(round(weight, 1), round(prev_weight, 1) if prev_weight else None, 'kg')}.")

    if not insights:
        return f"{greeting}\n\nNo major metrics logged yesterday."

    phrase = phrase_for(tags=["#Motivation"])
    sprinkles = [phrase_for(tags=["#Humour"]) for _ in range(random.randint(1, 2))]
    return f"{greeting}\n\n" + narrative_utils.stitch_sentences(insights, [phrase] + sprinkles)


def build_weekly_narrative(metrics: Dict[str, Any]) -> str:
    days = metrics.get("days", {})
    if not days:
        return "Howdy Ric 🤠\n\nNo logs found for last week. Rest week?"

    today = datetime.utcnow().date()
    all_dates = sorted(days.keys())
    sample_pairs: List[tuple[date, Dict[str, Any]]] = []
    for iso_day in all_dates:
        parsed_day = converters.to_date(iso_day)
        if parsed_day is None:
            continue
        payload = days.get(iso_day)
        if isinstance(payload, dict):
            sample_pairs.append((parsed_day, payload))
    sample_pairs.sort(key=lambda item: item[0])


    last_week = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, 8)]
    prev_week = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(8, 15)]

    week_data = [days[d] for d in last_week if d in days]
    prev_data = [days[d] for d in prev_week if d in days]

    greeting = random.choice([
        "Howdy Ric 🤠",
        "Ey up Ric 👋",
        "Another week down, mate!"
    ])

    insights: List[str] = []

    # Strength
    total_vol = sum(ex["volume_kg"] for day in week_data for ex in day.get("strength", []))
    prev_vol = sum(ex["volume_kg"] for day in prev_data for ex in day.get("strength", [])) if prev_data else None
    if total_vol:
        insights.append(f"Lifting volume hit {compare_text(int(total_vol), int(prev_vol) if prev_vol else None, 'kg')} this week.")

    # Steps
    total_steps = sum(day.get("activity", {}).get("steps", 0) for day in week_data)
    prev_steps = sum(day.get("activity", {}).get("steps", 0) for day in prev_data) if prev_data else None
    if total_steps:
        insights.append(f"You clocked {compare_text(int(total_steps), prev_steps, 'steps', 'this week')}.")

    # Sleep
    sleep_minutes = [day.get("sleep", {}).get("asleep_minutes", 0) for day in week_data]
    prev_sleep = [day.get("sleep", {}).get("asleep_minutes", 0) for day in prev_data] if prev_data else []
    if sleep_minutes:
        avg_sleep = round(sum(sleep_minutes) / len(sleep_minutes) / 60)
        prev_avg = round(sum(prev_sleep) / len(prev_sleep) / 60) if prev_sleep else None
        insights.append(f"Average sleep was {compare_text(avg_sleep, prev_avg, 'h', 'per night')}.")


    # Body composition
    def _extract_body_metric(day: Dict[str, Any], field: str) -> Optional[float]:
        body_section = day.get("body")
        if isinstance(body_section, dict):
            value = body_section.get(field)
        else:
            value = None
        if value is None:
            value = day.get(field)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _extract_body_age(day: Dict[str, Any]) -> Optional[float]:
        return _extract_body_metric(day, "body_age_years")

    muscle_week: List[float] = []
    for day in week_data:
        value = _extract_body_metric(day, "muscle_pct")
        if value is not None:
            muscle_week.append(value)

    muscle_prev: List[float] = []
    if prev_data:
        for day in prev_data:
            value = _extract_body_metric(day, "muscle_pct")
            if value is not None:
                muscle_prev.append(value)

    if muscle_week:
        avg_muscle = round(sum(muscle_week) / len(muscle_week), 1)
        avg_muscle_prev = round(sum(muscle_prev) / len(muscle_prev), 1) if muscle_prev else None
        if avg_muscle_prev is None:
            insights.append(f"Muscle composition averaged {avg_muscle:.1f}% this week.")
        else:
            diff = round(avg_muscle - avg_muscle_prev, 1)
            if abs(diff) >= 0.5:
                direction = "up" if diff > 0 else "down"
                insights.append(
                    f"Muscle composition averaged {avg_muscle:.1f}% this week, {direction} {abs(diff):.1f}% from last week."
                )

    body_age_week: List[float] = []
    for day in week_data:
        value = _extract_body_age(day)
        if value is not None:
            body_age_week.append(value)

    body_age_prev: List[float] = []
    if prev_data:
        for day in prev_data:
            value = _extract_body_age(day)
            if value is not None:
                body_age_prev.append(value)

    if body_age_week:
        avg_current = round(sum(body_age_week) / len(body_age_week), 1)
        avg_prev = round(sum(body_age_prev) / len(body_age_prev), 1) if body_age_prev else None
        if avg_prev is None:
            insights.append(f"Body Age averaged {avg_current:.1f}y this week.")
        else:
            diff = round(avg_current - avg_prev, 1)
            if diff > 0:
                insights.append(f"Body Age averaged {avg_current:.1f}y this week, up {abs(diff):.1f}y from last week.")
            elif diff < 0:
                insights.append(f"Body Age averaged {avg_current:.1f}y this week, down {abs(diff):.1f}y from last week.")
            else:
                insights.append(f"Body Age averaged {avg_current:.1f}y this week, matching last week.")

    trend_lines: List[str] = []
    if sample_pairs:
        trend_as_of = min(today - timedelta(days=1), sample_pairs[-1][0])
        trend_lines = compute_trend_lines(sample_pairs, as_of=trend_as_of, limit=2)
    if trend_lines:
        first_line, *extra_lines = trend_lines
        insights.append(f"Momentum backdrop - {first_line}")
        insights.extend(extra_lines)

    if not insights:
        return f"{greeting}\n\nQuiet week logged — recovery matters too."

    phrase = phrase_for(tags=["#Motivation"])
    sprinkles = [phrase_for(tags=["#Humour"]) for _ in range(random.randint(1, 2))]
    return f"{greeting}\n\n" + narrative_utils.stitch_sentences(insights, [phrase] + sprinkles)


def build_cycle_narrative(metrics: Dict[str, Any]) -> str:
    days = metrics.get("days", {})
    if not days:
        return "Ey up Ric 👋\n\nNo logs found for last cycle."

    all_dates = sorted(days.keys())
    cycle_days = settings.CYCLE_DAYS
    cycle_data = [days[d] for d in all_dates[-cycle_days:]]
    prev_cycle = [days[d] for d in all_dates[-2 * cycle_days:-cycle_days]] if len(all_dates) > cycle_days else []

    greeting = random.choice([
        "Ey up Ric 👋",
        "Cycle wrap-up time 🔄",
        "Alright Ric, here’s how the block went 💪"
    ])

    insights: List[str] = []

    # Strength
    total_vol = sum(ex["volume_kg"] for day in cycle_data for ex in day.get("strength", []))
    prev_vol = sum(ex["volume_kg"] for day in prev_cycle for ex in day.get("strength", [])) if prev_cycle else None
    if total_vol:
        insights.append(f"Cycle lifting came to {compare_text(int(total_vol), int(prev_vol) if prev_vol else None, 'kg')}.")

    # Cardio
    total_km = sum(day.get("activity", {}).get("distance_km", 0) for day in cycle_data)
    prev_km = sum(day.get("activity", {}).get("distance_km", 0) for day in prev_cycle) if prev_cycle else None
    if total_km:
        insights.append(f"Cardio totalled {compare_text(round(total_km), round(prev_km) if prev_km else None, 'km')}.")

    # Sleep
    sleep_minutes = [day.get("sleep", {}).get("asleep_minutes", 0) for day in cycle_data]
    prev_sleep = [day.get("sleep", {}).get("asleep_minutes", 0) for day in prev_cycle] if prev_cycle else []
    if sleep_minutes:
        avg_sleep = round(sum(sleep_minutes) / len(sleep_minutes) / 60)
        prev_avg = round(sum(prev_sleep) / len(prev_sleep) / 60) if prev_sleep else None
        insights.append(f"Average sleep was {compare_text(avg_sleep, prev_avg, 'h', 'per night')}.")

    if not insights:
        return f"{greeting}\n\nCycle was light on data — maybe deload phase?"

    phrase = phrase_for(tags=["#Motivation"])
    sprinkles = [phrase_for(tags=["#Humour"]) for _ in range(random.randint(1, 3))]
    return f"{greeting}\n\n" + narrative_utils.stitch_sentences(insights, [phrase] + sprinkles)


# -------------------------------------------------------------------------
# Plan summaries
# -------------------------------------------------------------------------

def build_weekly_plan_summary(
    plan_week_data: List[Dict[str, Any]],
    week_number: int,
    *,
    week_start: date | None = None,
) -> str:
    if not plan_week_data:
        return _no_plan_message(week_number)

    bullets, rest_days = _format_weekly_workouts(plan_week_data)
    rest_line = _format_rest_line(rest_days)
    if rest_line:
        bullets.append(rest_line)

    if not bullets:
        bullets = ["- No scheduled sessions landed – let's map some training blocks."]

    closers = [f"Coach's call: Week {week_number} is all about momentum - lock it in."]
    closers.extend(
        _closing_phrases(
            ["#Motivation"],
            "Remember: consistency beats intensity every time.",
            secondary_tags=["#Humour"],
            secondary_fallback="Keep the banter high and the stress low.",
        )
    )

    message = CoachMessage(
        greeting=helpers.choose_from(_COACH_WEEKLY_GREETINGS, "Coach Pete here"),
        heading=_format_weekly_heading(week_number, week_start),
        bullets=bullets,
        narrative=[],
        closers=closers,
    )
    return message.render()


# -------------------------------------------------------------------------
# Nudges & Facade
# -------------------------------------------------------------------------

_CUSTOM_NUDGE_PHRASES = {
    "#WithingsCheck": [
        "Scale's been quiet for a few days - fancy a Withings check-in?",
        "No Withings weigh-ins lately; hop on the scale and keep me posted.",
    ],
    "#HighStrainRest": [
        "You've been redlining lately; schedule a softer day so the gains stick.",
        "That strain streak is huge. Let's bank it with some extra recovery.",
    ],
    "#PersonalBest": [
        "New PB unlocked! Celebrate it and keep the form sharp.",
        "Personal bests raining down! Absolute scenes.",
    ],
}

def build_nudge(tag: str, sprinkles: List[str] | None = None, mode: str = "balanced") -> str:
    """Build a cheeky nudge narrative based on a phrase tag."""
    library = _CUSTOM_NUDGE_PHRASES.get(tag)
    if library:
        base_phrase = random.choice(library)
    else:
        base_phrase = phrase_for(tags=[tag])
    log_message(f"Pete nudge [{tag}] → {base_phrase}", "INFO")  # 👈 log which phrase was used

    extra = sprinkles or []
    return narrative_utils.stitch_sentences([base_phrase], extra, short_mode=False)


class PeteVoice:
    """Facade for Pete’s narrative output."""

    @staticmethod
    def daily(metrics: Dict[str, Any]) -> str:
        return build_daily_narrative(metrics)

    @staticmethod
    def weekly(metrics: Dict[str, Any]) -> str:
        return build_weekly_narrative(metrics)

    @staticmethod
    def cycle(metrics: Dict[str, Any]) -> str:
        return build_cycle_narrative(metrics)

    @staticmethod
    def plan(
        plan_week_data: List[Dict[str, Any]],
        week_number: int,
        week_start: date | None = None,
    ) -> str:
        return build_weekly_plan_summary(
            plan_week_data,
            week_number,
            week_start=week_start,
        )

    @staticmethod
    def nudge(tag: str, sprinkles: List[str] | None = None) -> str:
        return build_nudge(tag, sprinkles)

class NarrativeBuilder:
    """Compatibility wrapper around the narrative helper functions."""

    def build_daily_summary(self, summary_data: Dict[str, Any]) -> str:
        if not summary_data:
            return _no_daily_metrics_message()

        snapshot = dict(summary_data)
        day_value = converters.to_date(snapshot.get("date"))
        heading = _format_daily_heading(day_value)

        bullet_lines: List[str] = []
        for key in _DAILY_METRIC_ORDER:
            formatter = _DAILY_METRIC_BUILDERS.get(key)
            if not formatter:
                continue
            line = formatter(snapshot.get(key))
            if line:
                bullet_lines.append(f"- {line}")

        env_line = _format_environment_line(snapshot)
        if env_line:
            bullet_lines.append(f"- {env_line}")

        if not bullet_lines:
            bullet_lines.append("- No fresh metrics landed – give your trackers a sync and shout me once it's in.")

        readiness_line = _format_readiness_line(snapshot)
        narrative = [readiness_line] if readiness_line else []

        closers = _closing_phrases(
            ["#Motivation"],
            "Consistency is queen, volume is king!",
            secondary_tags=["#Humour"],
            secondary_fallback="Keep the energy cheeky and the effort honest.",
        )

        message = CoachMessage(
            greeting=helpers.choose_from(_COACH_GREETINGS, "Coach Pete checking in"),
            heading=heading,
            bullets=bullet_lines,
            narrative=narrative,
            closers=closers,
        )
        return message.render()

    def build_weekly_plan(
        self,
        plan_week_data: List[Dict[str, Any]],
        week_number: int,
        week_start: date | None = None,
    ) -> str:
        return build_weekly_plan_summary(
            plan_week_data,
            week_number,
            week_start=week_start,
        )
