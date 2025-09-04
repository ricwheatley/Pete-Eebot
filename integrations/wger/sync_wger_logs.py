#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
import json
import os
import csv
import requests
from typing import Optional, Any, Dict, List, Tuple

# -----------------------------
# Config
# -----------------------------
API_KEY = os.getenv("WGER_API_KEY")
CSV_PATH = Path(os.getenv("WORKOUT_LOG_CSV", "knowledge/workout_log.csv")).resolve()
DAYS_DIR = Path("docs/wger/days").resolve()
HISTORY_PATH = Path("docs/wger/history.json").resolve()
DAILY_PATH = Path("docs/wger/daily.json").resolve()
TRAINING_STATS_PATH = Path("knowledge/training_stats.csv").resolve()

BASE = "https://wger.de/api/v2"
HDRS = {"Authorization": f"Token {API_KEY}" if API_KEY else "", "Accept": "application/json"}

# -----------------------------
# Helpers
# -----------------------------
def to_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        try:
            return int(round(value))
        except Exception:
            return None
    if isinstance(value, str):
        s = value.strip()
        if s == "":
            return None
        try:
            f = float(s.replace(",", ""))
            return int(round(f))
        except Exception:
            return None
    return None

def to_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
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

def safe_sum_int(values: List[Optional[int]]) -> int:
    return sum(v for v in values if isinstance(v, int))

def safe_sum_float(values: List[Optional[float]]) -> float:
    return float(sum(v for v in values if isinstance(v, (int, float))))

def fetch_paginated_data(url: str, headers: dict) -> Optional[List[dict]]:
    results: List[dict] = []
    next_url = url
    page = 1
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
                if isinstance(data, dict):
                    results.append(data)
                next_url = None
            page += 1
        except requests.exceptions.RequestException as e:
            print(f"Error fetching {next_url}: {e}")
            return None
    return results

def english_exercise_name(ex: dict) -> str:
    trs = ex.get("translations") or []
    for t in trs:
        if t.get("language") == 2 and t.get("name"):
            return t["name"]
    if ex.get("name"):
        return ex["name"]
    return f"Exercise {ex.get('id', '?')}"

def ensure_dirs():
    for p in [CSV_PATH.parent, DAYS_DIR, HISTORY_PATH.parent, TRAINING_STATS_PATH.parent]:
        p.mkdir(parents=True, exist_ok=True)

def write_json(p: Path, payload: Any):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✔ Wrote {p} ({p.stat().st_size} bytes)")

# -----------------------------
# Main
# -----------------------------
def main():
    if not API_KEY:
        print("❌ WGER_API_KEY secret not found.")
        exit(1)

    ensure_dirs()

    print("🚀 Starting wger sync...")
    print(f"Output directories, CSV_PATH={CSV_PATH}, DAYS_DIR={DAYS_DIR}, HISTORY_PATH={HISTORY_PATH}, DAILY_PATH={DAILY_PATH}")

    # 1) Exercise DB
    print("Fetching exercise database for enrichment...")
    exercise_info_url = f"{BASE}/exerciseinfo/?language=2&limit=100"
    all_exercises = fetch_paginated_data(exercise_info_url, HDRS)
    if all_exercises is None:
        print("❌ Failed to fetch exercise database. Aborting.")
        exit(1)
    exercise_lookup: Dict[int, Dict[str, str]] = {}
    for ex in all_exercises:
        ex_id = ex.get("id")
        if ex_id is None:
            continue
        exercise_lookup[ex_id] = {
            "name": english_exercise_name(ex),
            "category": (ex.get("category") or {}).get("name", "N/A")
        }
    print(f"Created lookup for {len(exercise_lookup)} exercises.")

    # 2) Workout logs
    print("Fetching executed workout logs...")
    logs_url = f"{BASE}/workoutlog/?limit=200&ordering=-date"
    all_logs = fetch_paginated_data(logs_url, HDRS)
    if all_logs is None:
        print("❌ Failed to fetch workout logs. Aborting.")
        exit(1)
    print(f"Fetched {len(all_logs)} total logs from API.")

    # 3) Filter last 7 days
    # Note: use naive local date to avoid off-by-one vs UTC for all-day-like dates
    today = datetime.now().date()
    start_date = today - timedelta(days=6)

    def parse_date(d: str) -> Optional[datetime.date]:
        if not d:
            return None
        try:
            return datetime.fromisoformat(d[:10]).date()
        except ValueError:
            return None

    recent_logs: List[dict] = []
    for log in all_logs:
        date_str = (log.get("date") or log.get("created") or "")
        d = parse_date(date_str)
        if d and start_date <= d <= today:
            log["_date"] = d.isoformat()
            log["_reps"] = to_int(log.get("repetitions", log.get("reps")))
            log["_weight"] = to_float(log.get("weight"))
            recent_logs.append(log)

    print(f"Found {len(recent_logs)} logs within {start_date.isoformat()} to {today.isoformat()}.")

    # 3b) Group by day
    by_day: Dict[str, List[dict]] = defaultdict(list)
    for log in recent_logs:
        by_day[log["_date"]].append(log)
    print(f"Days with data: {sorted(by_day.keys())}")

    # 4) Persist JSON, even if empty
    # Always write history.json and daily.json so there is a stable output for downstream consumers.
    history: Dict[str, List[dict]] = {}
    if HISTORY_PATH.exists():
        try:
            history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            history = {}

    # Write per-day files for days we actually have logs for
    for day, logs in by_day.items():
        day_path = DAYS_DIR / f"{day}.json"
        write_json(day_path, logs)
        history[day] = logs

    # Update and write history.json, daily.json regardless of whether by_day is empty
    write_json(HISTORY_PATH, history)

    if by_day:
        latest_day = max(by_day.keys())
        write_json(DAILY_PATH, by_day[latest_day])
        print(f"Latest day is {latest_day}")
    else:
        # If no logs in the last 7 days, still produce an empty daily.json to make consumers happy
        write_json(DAILY_PATH, [])
        print("No logs in the last 7 days, wrote empty daily.json")

    # 5) CSV aggregation for new rows based on recent logs only
    header = ["date", "exercise_name", "category", "reps", "weight_kg"]
    processed_rows: List[Dict[str, Any]] = []
    for log in recent_logs:
        ex_id = log.get("exercise")
        details = exercise_lookup.get(ex_id, {})
        processed_rows.append({
            "date": log["_date"],
            "exercise_name": details.get("name", f"Unknown ID: {ex_id}"),
            "category": details.get("category", "N/A"),
            "reps": log.get("_reps") if log.get("_reps") is not None else "",
            "weight_kg": log.get("_weight") if log.get("_weight") is not None else "",
        })

    existing = set()
    if CSV_PATH.exists():
        with open(CSV_PATH, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing.add(tuple(row.get(k, "") for k in header))

    new_rows: List[Dict[str, Any]] = []
    for r in sorted(processed_rows, key=lambda x: x["date"] or ""):
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
        print(f"✔ Updated {CSV_PATH}")
    else:
        print("No new workout sets to add.")

    # 6) Training stats, computed from recent by_day only
    stats_header = [
        "date", "exercise_name", "total_reps", "total_volume",
        "max_lift_weight", "estimated_1RM",
    ]
    stats_data: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for day, logs in by_day.items():
        per_ex: Dict[str, List[Dict[str, Optional[float]]]] = defaultdict(list)
        for log in logs:
            ex_id = log.get("exercise")
            details = exercise_lookup.get(ex_id, {})
            name = details.get("name", f"Unknown ID: {ex_id}")
            per_ex[name].append({"reps": to_int(log.get("_reps")), "weight": to_float(log.get("_weight"))})

        for name, sets in per_ex.items():
            reps_list = [s["reps"] for s in sets if isinstance(s["reps"], int)]
            weights_list = [s["weight"] for s in sets if isinstance(s["weight"], (int, float))]
            total_reps = safe_sum_int(reps_list)
            total_volume = safe_sum_float([float(s["reps"]) * float(s["weight"]) for s in sets
                                           if isinstance(s["reps"], int) and isinstance(s["weight"], (int, float))])
            max_weight = max(weights_list) if weights_list else 0.0
            heaviest = max((s for s in sets if isinstance(s.get("weight"), (int, float))), key=lambda s: s["weight"], default=None)
            hw = float(heaviest["weight"]) if heaviest else 0.0
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

    existing_stats: Dict[Tuple[str, str], Dict[str, str]] = {}
    if TRAINING_STATS_PATH.exists():
        with open(TRAINING_STATS_PATH, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_stats[(row["date"], row["exercise_name"])] = row

    for key, val in stats_data.items():
        existing_stats[key] = {k: str(v) for k, v in val.items()}

    with open(TRAINING_STATS_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=stats_header)
        writer.writeheader()
        for row in sorted(existing_stats.values(), key=lambda r: (r["date"], r["exercise_name"])):
            writer.writerow(row)
    print(f"✔ Wrote stats to {TRAINING_STATS_PATH}")

    print("✅ Sync complete.")

# Entry
if __name__ == "__main__":
    main()