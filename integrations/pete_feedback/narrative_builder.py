import random
from .catchphrases import random_phrase
from .utils import stitch_sentences


def build_daily_narrative(metrics: dict) -> str:
    days = metrics.get("days", {})
    if not days:
        return "No logs found for yesterday. Did you rest? 😴"

    # Yesterday’s date
    yesterday = sorted(days.keys())[-1]
    data = days[yesterday]

    heading = f"🌞💪 Daily Sweat Sermon | {random_phrase(mode='serious')}"
    insights = []

    # Strength summary
    if "strength" in data:
        total_volume = sum(ex["volume_kg"] for ex in data["strength"])
        top_lift = max(data["strength"], key=lambda x: x["volume_kg"])
        insights.append(f"Strength totalled {int(total_volume)}kg lifted, led by {top_lift['exercise_name']} 🏋️")

    # Activity (Apple)
    if "activity" in data:
        steps = data["activity"].get("steps")
        dist = data["activity"].get("distance_km")
        mins = data["activity"].get("exercise_minutes")
        if steps:
            insights.append(f"You walked {steps:,} steps 🚶")
        if dist:
            insights.append(f"Covered {dist} km 🌍")
        if mins:
            insights.append(f"Logged {mins} minutes of exercise ⏱️")

    # Heart
    if "heart" in data:
        hr = data["heart"].get("resting_bpm")
        if hr:
            insights.append(f"Resting HR steady at {hr} bpm ❤️")

    # Sleep
    if "sleep" in data:
        sleep = data["sleep"].get("asleep_minutes")
        if sleep:
            hrs = round(sleep / 60, 1)
            insights.append(f"Slept {hrs} hrs 😴")

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

    if not insights:
        return f"{heading}\n\nNothing logged yesterday — maybe a rest day 🛌"

    sprinkles = [random_phrase(mode="chaotic") for _ in range(random.randint(2, 4))]
    return f"{heading}\n\n" + stitch_sentences(insights, sprinkles)


def build_weekly_narrative(metrics: dict) -> str:
    heading = f"📅 Weekly Grind Recap | {random_phrase(kind='coachism')}"
    return heading + "\n\n(stub — summarise last 7 days)"


def build_cycle_narrative(metrics: dict) -> str:
    heading = f"🔥 Training Cycle Reflections | {random_phrase(kind='metaphor')}"
    return heading + "\n\n(stub — summarise last cycle)"
