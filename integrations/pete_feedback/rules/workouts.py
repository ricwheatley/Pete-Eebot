import random

def interpret(metrics: dict) -> str:
    val = metrics.get("workouts")
    if not val:
        return ""
    phrases = [
        f"you smashed {val} workout(s) 🏋️‍♂️",
        f"{val} session(s) logged in the sweat bank",
        f"{val} workouts — Pete’s clipboard is proud",
        f"training tally: {val}, reps on reps",
        f"{val} sets of grind, no excuses",
    ]
    return random.choice(phrases)