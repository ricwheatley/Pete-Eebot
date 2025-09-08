import random
from .catchphrases import random_phrase
from .rules import weight, steps, workouts, recovery, body_age

def build_daily_narrative(metrics: dict) -> str:
    parts = []

    # --- Serious insight (60%)
    parts.append(weight.interpret(metrics))
    parts.append(steps.interpret(metrics))
    parts.append(workouts.interpret(metrics))
    parts.append(recovery.interpret(metrics))
    parts.append(body_age.interpret(metrics))

    # --- Pete’s extras (40%)
    extras = []
    for _ in range(random.randint(2, 5)):
        extras.append(random_phrase(random.choice(
            ["motivational", "silly", "portmanteau", "metaphor", "coachism"]
        )))
    parts.extend(extras)

    return "\n".join([p for p in parts if p])

def build_weekly_narrative(metrics: dict) -> str:
    parts = []
    parts.append("📅 Weekly Check-in:")

    # Serious part
    parts.append(weight.interpret(metrics))
    parts.append(workouts.interpret(metrics))  # aggregated weekly stats
    parts.append(steps.interpret(metrics))
    parts.append(recovery.interpret(metrics))
    parts.append(body_age.interpret(metrics))

    # Pete’s thematic nonsense
    theme = random_phrase("portmanteau")
    parts.append(f"This week’s theme: **{theme}** 🎉")

    for _ in range(random.randint(3, 6)):
        parts.append(random_phrase())

    return "\n".join([p for p in parts if p])

def build_cycle_narrative(metrics: dict) -> str:
    parts = []
    parts.append("🚀 4-Week Cycle Review:")

    # Core insights
    parts.append(weight.interpret(metrics))
    parts.append(workouts.interpret(metrics))
    parts.append(body_age.interpret(metrics))
    parts.append(recovery.interpret(metrics))

    # Pete goes full theatre mode here
    ridiculous = random_phrase("metaphor")
    parts.append(ridiculous)

    # Add a handful of extra phrases (Pete gets chatty here)
    for _ in range(random.randint(5, 8)):
        parts.append(random_phrase())

    return "\n".join([p for p in parts if p])