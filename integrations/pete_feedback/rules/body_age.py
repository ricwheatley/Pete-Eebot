import random

def interpret(metrics: dict) -> str:
    val = metrics.get("body_age_years")
    delta = metrics.get("age_delta_years")
    if not val:
        return ""
    if delta is None:
        delta_text = ""
    elif delta < 0:
        delta_text = f"({abs(delta):.1f} years younger than chrono)"
    elif delta > 0:
        delta_text = f"({abs(delta):.1f} years older than chrono)"
    else:
        delta_text = "(same as chrono)"

    phrases = [
        f"body age: {val:.1f} years {delta_text} 🔥",
        f"your body clock reads {val:.1f} — {delta_text}",
        f"fitness age at {val:.1f} {delta_text}",
        f"Pete’s verdict: {val:.1f} years {delta_text}",
        f"biological odometer shows {val:.1f} {delta_text}",
    ]
    return random.choice(phrases)