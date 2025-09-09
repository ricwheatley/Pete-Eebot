import json
import pathlib
import csv
from datetime import datetime, timedelta

# Paths
DOCS_DIR = pathlib.Path("docs")
KNOWLEDGE_DIR = pathlib.Path("knowledge")
DAILY_DIR = KNOWLEDGE_DIR / "daily"
HISTORY_PATH = KNOWLEDGE_DIR / "history.json"
EXERCISES_CSV = pathlib.Path("integrations/wger/catalog/exercises_en.csv")


def load_json(path: pathlib.Path):
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_json(path: pathlib.Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def load_exercise_catalog():
    catalog = {}
    if not EXERCISES_CSV.exists():
        return catalog
    with open(EXERCISES_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                catalog[int(row["id"])] = {
                    "name": row["name"],
                    "category": row["category"]
                }
            except ValueError:
                continue
    return catalog


def parse_wger_day(date: str, catalog: dict) -> list:
    """Parse WGER raw JSON logs into grouped exercise summaries."""
    path = DOCS_DIR / "wger" / "days" / f"{date}.json"
    if not path.exists():
        return []

    raw_logs = load_json(path)
    grouped = {}
    for entry in raw_logs:
        ex_id = entry.get("exercise")
        if not ex_id:
            continue
        reps = int(float(entry.get("repetitions", 0)))
        weight = float(entry.get("weight") or 0)

        if ex_id not in grouped:
            grouped[ex_id] = {
                "exercise_id": ex_id,
                "exercise_name": catalog.get(ex_id, {}).get("name", f"Exercise {ex_id}"),
                "category": catalog.get(ex_id, {}).get("category", "Unknown"),
                "sets": 0,
                "reps": [],
                "weights_kg": [],
                "volume_kg": 0
            }
        g = grouped[ex_id]
        g["sets"] += 1
        g["reps"].append(reps)
        g["weights_kg"].append(weight)
        g["volume_kg"] += reps * weight

    return list(grouped.values())


def parse_withings_day(date: str) -> dict:
    path = DOCS_DIR / "withings" / "days" / f"{date}.json"
    if not path.exists():
        return {}
    raw = load_json(path)
    return {
        "weight_kg": float(raw.get("weight_kg")) if raw.get("weight_kg") else None,
        "body_fat_pct": float(raw.get("body_fat_pct")) if raw.get("body_fat_pct") else None,
        "muscle_mass_kg": float(raw.get("muscle_mass_kg")) if raw.get("muscle_mass_kg") else None,
        "water_pct": float(raw.get("water_pct")) if raw.get("water_pct") else None
    }


def parse_apple_day(date: str) -> dict:
    path = DOCS_DIR / "apple" / "days" / f"{date}.json"
    if not path.exists():
        return {}
    raw = load_json(path)
    return {
        "activity": {
            "steps": raw.get("steps"),
            "exercise_minutes": raw.get("exercise_minutes"),
            "stand_minutes": raw.get("stand_minutes"),
            "distance_km": round(raw.get("distance_m", 0) / 1000, 2),
            "calories": {
                "active": raw.get("calories_active"),
                "resting": raw.get("calories_resting"),
                "total": raw.get("calories_total")
            }
        },
        "heart": {
            "resting_bpm": raw.get("hr_resting"),
            "avg_bpm": raw.get("hr_avg"),
            "min_bpm": raw.get("hr_min"),
            "max_bpm": raw.get("hr_max")
        },
        "sleep": {
            "total_minutes": raw.get("sleep_minutes", {}).get("in_bed"),
            "asleep_minutes": raw.get("sleep_minutes", {}).get("asleep"),
            "rem_minutes": raw.get("sleep_minutes", {}).get("rem"),
            "deep_minutes": raw.get("sleep_minutes", {}).get("deep"),
            "core_minutes": raw.get("sleep_minutes", {}).get("core"),
            "awake_minutes": raw.get("sleep_minutes", {}).get("awake")
        }
    }


def parse_body_age_day(date: str) -> dict:
    path = DOCS_DIR / "analytics" / "body_age.json"
    if not path.exists():
        return {}
    raw = load_json(path)
    if raw.get("date") != date:
        return {}
    return {
        "body_age_years": raw.get("body_age_years"),
        "age_delta_years": raw.get("age_delta_years"),
        "subscores": raw.get("subscores", {}),
        "composite": raw.get("composite")
    }


def consolidate_day(date: str, catalog: dict) -> dict:
    day_data = {"date": date}

    # WGER workouts → normalised strength list
    strength = parse_wger_day(date, catalog)
    if strength:
        day_data["strength"] = strength

    # Withings → body composition
    body = parse_withings_day(date)
    if body:
        day_data["body"] = body

    # Apple → activity, heart, sleep
    apple = parse_apple_day(date)
    day_data.update(apple)

    # Body age
    body_age = parse_body_age_day(date)
    if body_age:
        day_data["body_age"] = body_age

    return day_data


def build_knowledge():
    today = datetime.utcnow().date()
    history = load_json(HISTORY_PATH)
    catalog = load_exercise_catalog()

    # Look back over the last 7 days
    for i in range(1, 8):
        day = today - timedelta(days=i)
        date_str = day.strftime("%Y-%m-%d")
        daily_data = consolidate_day(date_str, catalog)

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
