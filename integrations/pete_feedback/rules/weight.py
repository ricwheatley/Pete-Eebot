def interpret(metrics: dict) -> str:
    w = metrics.get("weight_kg")
    bf = metrics.get("body_fat_pct")
    if w is None:
        return "⚖️ Weight data missing."
    msg = f"⚖️ Weight: {w:.1f}kg"
    if bf is not None:
        msg += f" | Body fat: {bf:.1f}%"
    return msg