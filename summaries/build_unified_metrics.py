import json
import pathlib
from datetime import datetime, timedelta

# Paths
ANALYTICS_DIR = pathlib.Path("docs/analytics")
HISTORY_PATH = ANALYTICS_DIR / "history.json"
BODY_AGE_PATH = ANALYTICS_DIR / "body_age.json"
UNIFIED_PATH = ANALYTICS_DIR / "unified_metrics.json"

# Example stubs for other integrations (to be wired up properly)
APPLE_LOGS = pathlib.Path("summaries/apple.json")
WGER_LOGS = pathlib.Path("integrations/wger/logs")
WITHINGS_LOGS = pathlib.Path("summaries/withings.json")


def load_json(path: pathlib.Path):
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_json(path: pathlib.Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def consolidate_day(date: str, history: dict, body_age: dict) -> dict:
    """
    Build a unified snapshot for a single day.
    """
    out = {}

    # From history.json (training sessions)
    day_stats = history.get("days", {}).get(date, {})
    if "run" in day_stats:
        out["run"] = day_stats["run"]
    if "strength" in day_stats:
        out["strength"] = day_stats["strength"]

    # From withings/apple (TODO: merge when available)
    # Placeholder for now
    out["withings"] = {
        "weight_kg": None,
        "resting_hr": None,
        "sleep_hours": None,
    }

    # Body age
    if date in body_age:
        out["body_age"] = body_age[date]

    return out


def build_unified_metrics():
    history = load_json(HISTORY_PATH)
    body_age = load_json(BODY_AGE_PATH)
    unified = load_json(UNIFIED_PATH)

    # Look back 7 days to refresh recent data
    today = datetime.utcnow().date()
    for i in range(1, 8):
        day = today - timedelta(days=i)
        date_str = day.strftime("%Y-%m-%d")
        snapshot = consolidate_day(date_str, history, body_age)
        if snapshot:
            unified[date_str] = snapshot

    save_json(UNIFIED_PATH, unified)
    print(f"Unified metrics updated: {len(unified)} days consolidated.")


if __name__ == "__main__":
    build_unified_metrics()
