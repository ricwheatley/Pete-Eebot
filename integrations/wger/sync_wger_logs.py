#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
import json
import os
import csv
import requests
from typing import Optional, Any, Dict, List

API_KEY = os.getenv("WGER_API_KEY")
CSV_PATH = Path(os.getenv("WORKOUT_LOG_CSV", "knowledge/workout_log.csv"))
DAYS_DIR = Path("docs/wger/days")
HISTORY_PATH = Path("docs/wger/history.json")
DAILY_PATH = Path("docs/wger/daily.json")
TRAINING_STATS_PATH = Path("knowledge/training_stats.csv")

if not API_KEY:
    print("❌ WGER_API_KEY secret not found.")
    exit(1)

BASE = "https://wger.de/api/v2"
HDRS = {"Authorization": f"Token {API_KEY}", "Accept": "application/json"}


# -----------------------------
# Helpers
# -----------------------------
def to_int(value: Any) -> Optional[int]:
    """Coerce value to int where possible. Return None for missing/invalid."""
    if value is None:
        return None
    if isinstance(value, bool):
        # Avoid treating True/False as 1/0
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        # Reps should be integral, but some APIs send 10.0 etc.
        try:
            return int(round(value))
        except Exception:
            return None
    if isinstance(value, str):
        s = value.strip()
        if s == "":
            return None
        try:
            # Allow "10", "10.0"
            f = float(s.replace(",", ""))
            return int(round(f))
        except Exception:
            return None
    return None


def to_float(value: Any) -> Optional[float]:
    """Coerce value to float where possible. Return None for missing/invalid."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if s == "":
            return None
        try:
            return float(s.replace(",", ""))
        except Exception:
            return None
    return None


def safe_sum_int(iterable: List[Optional[int]]) -> int:
    return sum(v for v in iterable if isinstance(v, int))


def safe_sum_float(iterable: List[Optional[float]]) -> float:
    return sum(v for v in iterable if isinstance(v, (int, float)))


def fetch_paginated_data(url: str, headers: dict):
    """Fetch all pages from an endpoint. Handles dict or list responses."""
    results = []
    next_url = url
    while next_url:
        try:
            r = requests.get(next_url, headers=headers, timeout=30)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and "results" in data:
                results.extend(data["results"])
                next_url = data.get("next")
            elif isinstance(data, list):
                results.extend(data)
                next_url = None
            else:
                # Unexpected shape, treat as single page
                if isinstance(data, dict):
                    results.append(data)
                next_url = None
        except requests.exceptions.RequestException as e:
            print(f"Error fetching {next_url}: {e}")
            return None
    return results


def english_exercise_name(ex: dict) -> str:
    """Prefer English translation, fall back to base 'name' or ID."""
    trs = ex.get("translations") or []
    for t in trs:
        # English is language==2 on wger.de
        if t.get("language") == 2 and t.get("name"):
            return t["name"]
    if ex.get("name"):
        return ex["name"]
    return f"Exercise {ex.get('id', '?')}"


# -----------------------------
# Main
# -----------------------------
def main():
    print("🚀 Starting wger sync...")
    headers = HDRS

    # --- 1. Fetch exercise database for enrichment (exerciseinfo has translations) ---
    print("Fetching exercise database for enrichment...")
    exercise_info_url = f"{BASE}/exerciseinfo/?language=2&limit=100"
    all_exercises = fetch_paginated_data(exercise_info_url, headers)
    if all_exercises is None:
        print("❌ Failed to fetch exercise database. Aborting.")
        exit(1)

    # Build ID -> {name, category} lookup
    exercise_lookup: Dict[int, Dict[str, str]] = {}
    for ex in all_exercises:
        ex_id = ex.get("id")
        if ex_id is None:
            continue
        name = english_exercise_name(ex)
        cat = (ex.get("category") or {}).get("name", "N/A")
        exercise_lookup[ex_id] = {"name": name, "category": cat}

    print(f"Created lookup for {len(exercise_lookup)} exercises.")

    # --- 2. Fetch executed workout logs (public endpoint is /workoutlog/) ---
    print("Fetching executed workout logs...")
    logs_url = f"{BASE}/workoutlog/?limit=200&ordering=-date"
    all_logs = fetch_paginated_data(logs_url, headers)
    if all_logs is None:
        print("❌ Failed to fetch workout logs. Aborting.")
        exit(1)
    if not all_logs:
        print("No workout logs found on wger.")
        return

    # --- 3. Filter last 7 days ---
    today = datetime.utcnow().date()
    start_date = today - timedelta(days=6)
    recent_logs = []
    for log in all_logs:
        date_str = (log.get("date") or log.get("created") or "")[:10]
        if not date_str:
            continue
        try:
            log_date = datetime.fromisoformat(date_str).date()
        except ValueError:
            continue
        if start_date <= log_date <= today:
            # Coerce reps/weight here so subsequent code can trust types
            reps_raw = log.get("repetitions", log.get("reps"))
            weight_raw = log.get("weight")
            log["_date"] = date_str
            log["_reps"] = to_int(reps_raw)          # int or None
            log["_weight"] = to_float(weight_raw)    # float or None
            recent_logs.append(log)

    if not recent_logs:
        print("No workout logs in the last 7 days.")
        return

    # Group by day for JSON outputs and stats
    by_day: Dict[str, List[dict]] = defaultdict(list)
    for log in recent_logs:
        by_day[log["_date"]].append(log)

    # Ensure output directories
    DAYS_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Save per-day logs and update history
    history: Dict[str, List[dict]] = {}
    if HISTORY_PATH.exists():
        try:
            history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            history = {}
    for day, logs in by_day.items():
        day_path = DAYS_DIR / f"{day}.json"
        day_path.write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")
        history[day] = logs

    HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

    latest_day = max(by_day.keys())
    DAILY_PATH.write_text(json.dumps(by_day[latest_day], ensure_ascii=False, indent=2), encoding="utf-8")

    # --- 4. Process logs into CSV rows ---
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    header = ["date", "exercise_name", "category", "reps", "weight_kg"]

    processed_rows: List[Dict[str, Any]] = []
    for log in recent_logs:
        ex_id = log.get("exercise")
        details = exercise_lookup.get(ex_id, {})
        name = details.get("name", f"Unknown ID: {ex_id}")
        cat = details.get("category", "N/A")
        reps = log.get("_reps")      # already int or None
        wt = log.get("_weight")      # already float or None
        processed_rows.append({
            "date": log["_date"],
            "exercise_name": name,
            "category": cat,
            "reps": reps if reps is not None else "",
            "weight_kg": wt if wt is not None else "",
        })

    existing = set()
    if CSV_PATH.exists():
        with open(CSV_PATH, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing.add(tuple(row.get(k, "") for k in header))

    new_rows = []
    for r in sorted(processed_rows, key=lambda x: x["date"] or ""):
        # Use str() for the dedupe key so that 10 and "10" compare consistently
        key = tuple(str(r.get(k, "")) for k in header)
        if key not in existing:
            new_rows.append(r)
            existing.add(key)

    if new_rows:
        print(f"Adding {len(new_rows)} new workout sets to {CSV_PATH}")
        is_new_file = not CSV_PATH.exists()
        with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            if is_new_file:
                writer.writeheader()
            writer.writerows(new_rows)
    else:
        print("No new workout sets to add.")

    # --- 5. Compute training stats per exercise/day ---
    stats_header = [
        "date",
        "exercise_name",
        "total_reps",
        "total_volume",
        "max_lift_weight",
        "estimated_1RM",
    ]
    stats_data: Dict[tuple, Dict[str, Any]] = {}
    for day, logs in by_day.items():
        per_ex: Dict[str, List[Dict[str, Optional[float]]]] = defaultdict(list)
        for log in logs:
            ex_id = log.get("exercise")
            details = exercise_lookup.get(ex_id, {})
            name = details.get("name", f"Unknown ID: {ex_id}")
            reps = to_int(log.get("_reps"))      # ensure int
            wt = to_float(log.get("_weight"))    # ensure float
            per_ex[name].append({"reps": reps, "weight": wt})

        for name, sets in per_ex.items():
            # Prepare numeric-only lists for aggregates
            reps_list = [s["reps"] for s in sets if isinstance(s["reps"], int)]
            weights_list = [s["weight"] for s in sets if isinstance(s["weight"], (int, float))]

            total_reps = safe_sum_int(reps_list)
            total_volume = safe_sum_float(
                [(float(s["reps"]) * float(s["weight"])) for s in sets
                 if isinstance(s["reps"], int) and isinstance(s["weight"], (int, float))]
            )
            max_weight = max(weights_list) if weights_list else 0.0

            # For 1RM, use the heaviest set with valid reps
            heaviest = None
            if sets:
                valid_sets = [s for s in sets if isinstance(s["weight"], (int, float))]
                if valid_sets:
                    heaviest = max(valid_sets, key=lambda s: s["weight"])
            hw = float(heaviest["weight"]) if heaviest and heaviest.get("weight") is not None else 0.0
            hr = int(heaviest["reps"]) if heaviest and isinstance(heaviest.get("reps"), int) else 0
            est_1rm = hw * (1 + hr / 30) if hw > 0 and hr > 0 else 0.0

            stats_data[(day, name)] = {
                "date": day,
                "exercise_name": name,
                "total_reps": int(total_reps),
                "total_volume": round(float(total_volume), 2),
                "max_lift_weight": round(float(max_weight), 2),
                "estimated_1RM": round(float(est_1rm), 2),
            }

    existing_stats: Dict[tuple, Dict[str, str]] = {}
    if TRAINING_STATS_PATH.exists():
        with open(TRAINING_STATS_PATH, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_stats[(row["date"], row["exercise_name"])] = row

    # Overwrite or insert with freshly computed stats
    for key, val in stats_data.items():
        existing_stats[key] = {
            "date": str(val["date"]),
            "exercise_name": str(val["exercise_name"]),
            "total_reps": str(val["total_reps"]),
            "total_volume": str(val["total_volume"]),
            "max_lift_weight": str(val["max_lift_weight"]),
            "estimated_1RM": str(val["estimated_1RM"]),
        }

    TRAINING_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TRAINING_STATS_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=stats_header)
        writer.writeheader()
        for row in sorted(existing_stats.values(), key=lambda r: (r["date"], r["exercise_name"])):
            writer.writerow(row)

    print("✅ Sync complete.")


if __name__ == "__main__":
    main()