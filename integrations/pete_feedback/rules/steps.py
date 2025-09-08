def interpret(metrics: dict) -> str:
    s = metrics.get("steps")
    if s is None:
        return "👟 Steps: data missing."
    return f"👟 Steps: {s:,} — keep moving!"