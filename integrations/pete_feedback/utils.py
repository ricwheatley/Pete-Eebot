import random

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

def stitch_sentences(insights, sprinkles, short_mode=False):
    """
    Turn insights + sprinkles into a chatty Pete-style rant.
    If short_mode=True, just return a single chaotic one-liner.
    """
    # ~5–10% chance to override with short rant
    if short_mode or random.random() < 0.08:
        return random.choice([
            "DOMS = proof you exist 💥",
            "Burpees? More like slurpees 🥤",
            "Your quads stomp harder than Godzilla in heels 🦖",
            "Proteinpalooza solves everything 🍗",
            "Squatmageddon is coming — brace yourself 🏋️‍♂️",
        ])

    text = []
    if insights:
        text.append(f"Mate, {insights[0]} — not bad at all.")

    for part in insights[1:]:
        connector = random.choice(CONNECTORS)
        text.append(f"{connector} {part}")

    for s in sprinkles:
        connector = random.choice(CONNECTORS)
        text.append(f"{connector} {s.lower()}")

    text.append(random.choice(CLOSERS))
    return " ".join(text)