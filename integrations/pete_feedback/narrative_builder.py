import random
from .catchphrases import phrase_for
from .utils import stitch_sentences


def build_daily_narrative(metrics: dict) -> str:
    days = metrics.get("days", {})
    if not days:
        return "No logs found for yesterday. Did you rest? 😴"

    # Yesterday’s date
    yesterday = sorted(days.keys())[-1]
    data = days[yesterday]

    tags = set(["#Motivation"])  # default fallback

    heading = f"🌞💪 Daily Sweat Sermon | {phrase_for(['#Motivation'])}"
    insights = []

    # Strength summary
    if "strength" in data:
        total_volume = sum(ex["volume_kg"] for ex in data["strength"])
        top_lift = max(data["strength"], key=lambda x: x["volume_kg"])
        insights.append(f"Strength totalled {int(total_volume)}kg lifted, led by {top_lift['exercise_name']} 🏋️")
        tags.add(f"#{top_lift['category']}")
        if any(ex.get("pr") for ex in data["strength"]):
            tags.add("#PR")

    # Activity (Apple)
    if "activity" in data:
        steps = data["activity"].get("steps")
        dist = data["activity"].get("distance_km")
        mins = data["activity"].get("exercise_minutes")
        if steps:
            insights.append(f"You walked {steps:,} steps 🚶")
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
            insights.append(f"Resting HR steady at {hr} bpm ❤️")
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
            insights.append(f"Body age sits at {ba} years (Δ {delta:+.1f}) 📊")
            tags.add("#Recovery")

    if not insights:
        return f"{heading}\n\nNothing logged yesterday — maybe a rest day 🛌"

    # Select a phrase matching yesterday's tags
    phrase = phrase_for(list(tags))

    sprinkles = [phrase_for(["#Humour"]) for _ in range(random.randint(1, 2))]
    return f"{heading}\n\n" + stitch_sentences(insights, [phrase] + sprinkles)


def build_weekly_narrative(metrics: dict) -> str:
    heading = f"📅 Weekly Grind Recap | {phrase_for(['#Coachism'])}"
    return heading + "\n\n(stub — summarise last 7 days)"


def build_cycle_narrative(metrics: dict) -> str:
    heading = f"🔥 Training Cycle Reflections | {phrase_for(['#Chaotic'])}"
    return heading + "\n\n(stub — summarise last cycle)"
