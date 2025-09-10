import random
from datetime import datetime, timedelta
from .phrase_picker import random_phrase as phrase_for
from .utils import stitch_sentences


def build_daily_narrative(metrics: dict) -> str:
    days = metrics.get("days", {})
    if not days:
        return "No logs found for yesterday. Did you rest? 😴"

    # Yesterday’s date
    yesterday = sorted(days.keys())[-1]
    data = days[yesterday]

    tags = set(["#Motivation"])  # default fallback

    heading = f"🌞💪 Daily Sweat Sermon | {phrase_for(tags=['#Motivation'])}"
    insights = []

    # Strength summary
    if "strength" in data:
        total_volume = sum(ex["volume_kg"] for ex in data["strength"])
        top_lift = max(data["strength"], key=lambda x: x["volume_kg"])
        insights.append(
            f"Strength totalled {int(total_volume)}kg lifted, led by {top_lift['exercise_name']} 💪"
        )
        tags.add(f"#{top_lift['category']}")
        if any(ex.get("pr") for ex in data["strength"]):
            tags.add("#PR")

    # Activity (Apple)
    if "activity" in data:
        steps = data["activity"].get("steps")
        dist = data["activity"].get("distance_km")
        mins = data["activity"].get("exercise_minutes")
        if steps:
            insights.append(f"You walked {steps:,} steps 🚶‍♂️")
            tags.add("#Cardio")
            tags.add("#Steps")
        if dist:
            insights.append(f"Covered {dist} km 🌍")
            tags.add("#Cardio")
        if mins:
            insights.append(f"Logged {mins} minutes of exercise ⏱️")

    # Heart
    if "heart" in data:
        hr = data["heart"].get("resting_bpm")
        if hr:
            insights.append(f"Resting HR steady at {hr} bpm 🫀")
            tags.add("#Recovery")

    # Sleep
    if "sleep" in data:
        sleep = data["sleep"].get("asleep_minutes")
        if sleep:
            hrs = round(sleep / 60, 1)
            insights.append(f"Slept {hrs} hrs 😴")
            tags.add("#Recovery")

    # Body (Withings)
    if "body" in data:
        w = data["body"].get("weight_kg")
        if w:
            insights.append(f"Weight recorded at {w} kg ⚖️")

    # Body age
    if "body_age" in data:
        ba = data["body_age"].get("body_age_years")
        delta = data["body_age"].get("age_delta_years")
        if ba:
            insights.append(f"Body age sits at {ba} years ({delta:+.1f}y) 🧬")
            tags.add("#Recovery")

    if not insights:
        return f"{heading}\n\nNothing logged yesterday — maybe a rest day 🛌"

    # Select a phrase matching yesterday's tags
    phrase = phrase_for(tags=list(tags))

    sprinkles = [phrase_for(tags=["#Humour"]) for _ in range(random.randint(1, 2))]
    return f"{heading}\n\n" + stitch_sentences(insights, [phrase] + sprinkles)


def build_weekly_narrative(metrics: dict) -> str:
    days = metrics.get("days", {})
    if not days:
        return "No logs found for last week. Rest week? 😴"

    today = datetime.utcnow().date()
    last_week = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, 8)]
    week_data = [days[d] for d in last_week if d in days]

    heading = f"🌟 Weekly Grind Recap | {phrase_for(tags=['#Coachism'])}"
    insights = []

    # Strength totals
    total_volume = sum(
        ex["volume_kg"]
        for day in week_data
        for ex in day.get("strength", [])
    )
    if total_volume:
        insights.append(f"Weekly strength volume hit {int(total_volume)}kg 🏋️")

    # Cardio totals
    total_km = sum(
        day.get("activity", {}).get("distance_km", 0)
        for day in week_data
    )
    if total_km:
        insights.append(f"Cardio covered {round(total_km, 1)} km 🏃‍♂️")

    # Sleep avg
    sleep_minutes = [
        day.get("sleep", {}).get("asleep_minutes", 0)
        for day in week_data
    ]
    if sleep_minutes:
        avg_sleep = round(sum(sleep_minutes) / len(sleep_minutes) / 60, 1)
        insights.append(f"Averaged {avg_sleep} hrs sleep 🛌")

    if not insights:
        return heading + "\n\nQuiet week logged — recovery matters too."

    phrase = phrase_for(tags=["#Motivation"])
    sprinkles = [phrase_for(tags=["#Humour"]) for _ in range(random.randint(1, 2))]
    return f"{heading}\n\n" + stitch_sentences(insights, [phrase] + sprinkles)


def build_cycle_narrative(metrics: dict) -> str:
    days = metrics.get("days", {})
    if not days:
        return "No logs found for last cycle. 💤"

    all_dates = sorted(days.keys())
    cycle_data = [days[d] for d in all_dates[-28:]]  # assume 4-week cycle

    heading = f"🔥 Training Cycle Reflections | {phrase_for(tags=['#Chaotic'])}"
    insights = []

    # Strength PRs in cycle
    prs = []
    for day in cycle_data:
        for ex in day.get("strength", []):
            if ex.get("pr"):
                prs.append(ex["exercise_name"])
    if prs:
        insights.append(f"PRs smashed this cycle: {', '.join(set(prs))} 🏆")

    # Volume total
    total_volume = sum(
        ex["volume_kg"]
        for day in cycle_data
        for ex in day.get("strength", [])
    )
    if total_volume:
        insights.append(f"Total strength volume this cycle: {int(total_volume)}kg 💪")

    # Distance total
    total_km = sum(
        day.get("activity", {}).get("distance_km", 0)
        for day in cycle_data
    )
    if total_km:
        insights.append(f"Total cardio distance: {round(total_km, 1)} km 🏃")

    if not insights:
        return heading + "\n\nCycle was light on data — maybe deload phase?"

    phrase = phrase_for(tags=["#Motivation"])
    sprinkles = [phrase_for(tags=["#Humour"]) for _ in range(random.randint(1, 3))]
    return f"{heading}\n\n" + stitch_sentences(insights, [phrase] + sprinkles)