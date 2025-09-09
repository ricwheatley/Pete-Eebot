import json
import pathlib
from datetime import datetime, timedelta

# Paths
DOCS_DIR = pathlib.Path("docs")
KNOWLEDGE_DIR = pathlib.Path("knowledge")
DAILY_DIR = KNOWLEDGE_DIR / "daily"
HISTORY_PATH = KNOWLEDGE_DIR / "history.json"


def load_json(path: pathlib.Path):
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_json(path: pathlib.Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def consolidate_day(date: str) -> dict:
    """
    Read raw integration snapshots for a given date and consolidate into one dictionary.
    """
    day_data = {"date": date}

    # WGER workouts
    wger_path = DOCS_DIR / "wger" / "days" / f"{date}.json"
    if wger_path.exists():
        day_data["wger"] = load_json(wger_path)

    # Withings data
    withings_path = DOCS_DIR / "withings" / "days" / f"{date}.json"
    if withings_path.exists():
        day_data["withings"] = load_json(withings_path)

    # Apple data
    apple_path = DOCS_DIR / "apple" / "days" / f"{date}.json"
    if apple_path.exists():
        day_data["apple"] = load_json(apple_path)

    return day_data


def build_knowledge():
    today = datetime.utcnow().date()
    history = load_json(HISTORY_PATH)

    # Look back over the last 7 days
    for i in range(1, 8):
        day = today - timedelta(days=i)
        date_str = day.strftime("%Y-%m-%d")
        daily_data = consolidate_day(date_str)

        if len(daily_data.keys()) > 1:  # Means we found at least one integration
            # Save daily file
            save_json(DAILY_DIR / f"{date_str}.json", daily_data)

            # Update history
            if "days" not in history:
                history["days"] = {}
            history["days"][date_str] = daily_data

    # Save updated history
    save_json(HISTORY_PATH, history)
    print(f"Knowledge updated: {len(history.get('days', {}))} days consolidated.")


if __name__ == "__main__":
    build_knowledge()
