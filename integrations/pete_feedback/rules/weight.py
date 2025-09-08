import random

def interpret(metrics: dict) -> str:
    val = metrics.get("weight_kg")
    if not val:
        return ""
    phrases = [
        f"you tipped the scales at {val:.1f}kg ⚖️",
        f"yesterday’s weight was {val:.1f}kg — not bad at all",
        f"the iron doesn’t lie: {val:.1f}kg on the books",
        f"body mass check-in: {val:.1f}kg, steady as she goes",
        f"{val:.1f}kg — gravity’s still working",
    ]
    return random.choice(phrases)