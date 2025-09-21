# (Functional) Builds daily/weekly/cycle summaries using domain metrics and phrases. *(Uses `phrase_picker` and `narrative_utils` to generate chatty text.)*

import random
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from pete_e.domain.phrase_picker import random_phrase as phrase_for
from pete_e.domain import narrative_utils
from pete_e.config import settings
from pete_e.infrastructure.log_utils import log_message


_DAY_NAMES = {
    1: "Monday",
    2: "Tuesday",
    3: "Wednesday",
    4: "Thursday",
    5: "Friday",
    6: "Saturday",
    7: "Sunday",
}


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


    # Body Age
    def _extract_body_age(day: Dict[str, Any]) -> Optional[float]:
        body_section = day.get("body")
        if isinstance(body_section, dict):
            value = body_section.get("body_age_years")
        else:
            value = None
        if value is None:
            value = day.get("body_age_years")
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

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

def build_weekly_plan_summary(plan_week_data: List[Dict[str, Any]], week_number: int) -> str:
    if not plan_week_data:
        return f"Week {week_number} doesn't have any scheduled training sessions yet."

    plan_days: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for entry in plan_week_data:
        day_number = entry.get("day_of_week")
        if not isinstance(day_number, int):
            continue
        plan_days[day_number].append(entry)

    summary_lines: List[str] = [f"Week {week_number} training plan:", ""]

    for day_number in range(1, 8):
        day_name = _DAY_NAMES.get(day_number, f"Day {day_number}")
        workouts = plan_days.get(day_number, [])

        if not workouts:
            summary_lines.append(f"{day_name}: Rest / recovery focus.")
            continue

        summary_lines.append(f"{day_name}:")
        for workout in workouts:
            exercise = workout.get("exercise_name") or f"Exercise {workout.get('exercise_id')}"
            sets = workout.get("sets")
            reps = workout.get("reps")
            rir = workout.get("rir")

            details: List[str] = []
            if sets is not None and reps is not None:
                details.append(f"{sets} x {reps}")
            if rir is not None:
                details.append(f"RIR {rir:g}")

            detail_text = f" ({', '.join(details)})" if details else ""
            summary_lines.append(f"  • {exercise}{detail_text}")

    summary_lines.append("")
    summary_lines.append(phrase_for(tags=["#Motivation"]))

    return "\n".join(summary_lines).strip()


# -------------------------------------------------------------------------
# Nudges & Facade
# -------------------------------------------------------------------------

def build_nudge(tag: str, sprinkles: List[str] | None = None, mode: str = "balanced") -> str:
    """Build a cheeky nudge narrative based on a phrase tag."""
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
    def plan(plan_week_data: List[Dict[str, Any]], week_number: int) -> str:
        return build_weekly_plan_summary(plan_week_data, week_number)

    @staticmethod
    def nudge(tag: str, sprinkles: List[str] | None = None) -> str:
        return build_nudge(tag, sprinkles)

class NarrativeBuilder:
    """Compatibility wrapper around the narrative helper functions."""

    def build_daily_summary(self, summary_data: Dict[str, Any]) -> str:
        if not summary_data:
            return "I could not find any data for that day."

        title = summary_data.get("date") or "Daily Summary"
        sections = []

        def add_metric(label: str, value: Any, suffix: str = "") -> None:
            if value is None:
                return
            sections.append(f"{label}: {value}{suffix}")

        add_metric("Weight", summary_data.get("weight_kg"), " kg")
        add_metric("Body fat", summary_data.get("body_fat_pct"), "%")
        add_metric("Resting HR", summary_data.get("hr_resting"), " bpm")
        add_metric("Steps", summary_data.get("steps"))
        add_metric("Active calories", summary_data.get("calories_active"))
        add_metric("Sleep", summary_data.get("sleep_asleep_minutes"), " min")

        readiness_label = summary_data.get("readiness_headline") or summary_data.get("readiness_state")
        if readiness_label:
            sections.append(f"Readiness: {str(readiness_label)}")
        readiness_tip = summary_data.get("readiness_tip")
        if readiness_tip:
            sections.append(f"Readiness tip: {str(readiness_tip)}")

        body = sections or ["No detailed metrics were recorded."]
        return f"{title}\n" + "\n".join(body)

    def build_weekly_plan(self, plan_week_data: List[Dict[str, Any]], week_number: int) -> str:
        return build_weekly_plan_summary(plan_week_data, week_number)
