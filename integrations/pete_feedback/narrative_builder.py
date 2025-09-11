import random
from datetime import datetime, timedelta
from .phrase_picker import random_phrase as phrase_for
from .utils import stitch_sentences


def compare_text(current, previous, unit="", context=""):
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


def build_daily_narrative(metrics: dict) -> str:
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

    insights = []

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
        insights.append(f"Weight came in at {compare_text(round(weight,1), round(prev_weight,1) if prev_weight else None, 'kg')}.")

    if not insights:
        return f"{greeting}\n\nNo major metrics logged yesterday."

    phrase = phrase_for(tags=["#Motivation"])
    sprinkles = [phrase_for(tags=["#Humour"]) for _ in range(random.randint(1, 2))]
    return f"{greeting}\n\n" + stitch_sentences(insights, [phrase] + sprinkles)


def build_weekly_narrative(metrics: dict) -> str:
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

    insights = []

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

    if not insights:
        return f"{greeting}\n\nQuiet week logged — recovery matters too."

    phrase = phrase_for(tags=["#Motivation"])
    sprinkles = [phrase_for(tags=["#Humour"]) for _ in range(random.randint(1, 2))]
    return f"{greeting}\n\n" + stitch_sentences(insights, [phrase] + sprinkles)


def build_cycle_narrative(metrics: dict) -> str:
    days = metrics.get("days", {})
    if not days:
        return "Ey up Ric 👋\n\nNo logs found for last cycle."

    all_dates = sorted(days.keys())
    cycle_data = [days[d] for d in all_dates[-28:]]
    prev_cycle = [days[d] for d in all_dates[-56:-28]] if len(all_dates) > 28 else []

    greeting = random.choice([
        "Ey up Ric 👋",
        "Cycle wrap-up time 🔄",
        "Alright Ric, here’s how the block went 💪"
    ])

    insights = []

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
    return f"{greeting}\n\n" + stitch_sentences(insights, [phrase] + sprinkles)