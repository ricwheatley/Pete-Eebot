import random

def interpret(metrics: dict) -> str:
    val = metrics.get("steps")
    if not val:
        return ""
    phrases = [
        f"you clocked {val:,} steps 👟",
        f"{val:,} steps — cardio corner approves",
        f"walking tall with {val:,} steps logged",
        f"steps yesterday: {val:,}, keeping the gains mobile",
        f"{val:,} little victories under your feet",
    ]
    return random.choice(phrases)