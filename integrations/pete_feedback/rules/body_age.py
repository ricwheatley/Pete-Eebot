def interpret(metrics: dict) -> str:
    ba = metrics.get("body_age_years")
    delta = metrics.get("age_delta_years")
    if ba is None:
        return "🔥 Body age not available."
    if delta is None:
        return f"🔥 Body age: {ba:.1f} years."
    sign = "younger" if delta < 0 else "older"
    return f"🔥 Body age: {ba:.1f} years ({abs(delta):.1f} years {sign} than chrono)."