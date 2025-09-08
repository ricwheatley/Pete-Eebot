def interpret(metrics: dict) -> str:
    w = metrics.get("workouts", [])
    if not w:
        return "🏋️ Training: rest day or no log."
    return f"🏋️ Training: {len(w)} session(s) logged."