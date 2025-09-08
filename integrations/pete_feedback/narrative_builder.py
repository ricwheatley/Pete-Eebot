import random
from .catchphrases import random_phrase
from .rules import weight, steps, workouts, recovery, body_age

CONNECTORS = [
    "mate,", "listen,", "honestly,", "you know what?",
    "I swear,", "look,", "trust me,", "real talk,"
]

CLOSERS = [
    "Keep grinding or the gains train leaves without you 🚂💪",
    "Hakuna matata and heavy squatta 🦁🏋️",
    "No excuses, just sets and juices 🥤💪",
    "The dumbbell of destiny calls your name 🔔",
    "Stay swole, stay soulful ✨",
]

def _stitch_sentences(insights, sprinkles):
    """Turn insights + sprinkles into a chatty paragraph."""
    text = []
    if insights:
        text.append(f"Mate, {insights[0]} — not bad at all.")

    # weave in the rest
    for part in insights[1:]:
        connector = random.choice(CONNECTORS)
        text.append(f"{connector} {part}")

    for s in sprinkles:
        connector = random.choice(CONNECTORS)
        text.append(f"{connector} {s.lower()}")

    text.append(random.choice(CLOSERS))
    return " ".join(text)


def build_daily_narrative(metrics: dict) -> str:
    heading = f"🌞 Daily Sweat Sermon | {random_phrase(mode='chaotic')}"
    insights = [
        weight.interpret(metrics),
        steps.interpret(metrics),
        workouts.interpret(metrics),
        recovery.interpret(metrics),
        body_age.interpret(metrics),
    ]
    insights = [i for i in insights if i]

    sprinkles = [random_phrase() for _ in range(random.randint(1, 3))]
    return f"{heading}\n\n{_stitch_sentences(insights, sprinkles)}"


def build_weekly_narrative(metrics: dict) -> str:
    heading = f"📅 Flex Friday Check-in | {random_phrase(kind='coachism')}"
    insights = [
        weight.interpret(metrics),
        workouts.interpret(metrics),
        steps.interpret(metrics),
        recovery.interpret(metrics),
        body_age.interpret(metrics),
        f"This week’s theme: {random_phrase('portmanteau')}"
    ]
    insights = [i for i in insights if i]

    sprinkles = [random_phrase(mode="chaotic") for _ in range(random.randint(2, 4))]
    return f"{heading}\n\n{_stitch_sentences(insights, sprinkles)}"


def build_cycle_narrative(metrics: dict) -> str:
    heading = f"🚀 Gainz Odyssey | {random_phrase(kind='metaphor')}"
    insights = [
        weight.interpret(metrics),
        workouts.interpret(metrics),
        body_age.interpret(metrics),
        recovery.interpret(metrics),
    ]
    insights = [i for i in insights if i]

    sprinkles = [random_phrase(mode="chaotic") for _ in range(random.randint(4, 6))]
    return f"{heading}\n\n{_stitch_sentences(insights, sprinkles)}"