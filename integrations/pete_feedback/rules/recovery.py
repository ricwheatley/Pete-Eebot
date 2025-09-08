def interpret(metrics: dict) -> str:
    sleep = metrics.get("sleep_hours")
    rhr = metrics.get("hr_resting")
    if sleep is None and rhr is None:
        return "😴 Recovery data missing."
    parts = []
    if sleep:
        parts.append(f"Sleep: {sleep:.1f}h")
    if rhr:
        parts.append(f"Resting HR: {rhr}bpm")
    return "😴 " + " | ".join(parts)