#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import os
import csv
import requests

API_KEY = os.getenv("WGER_API_KEY")
CSV_PATH = Path(os.getenv("WORKOUT_LOG_CSV", "knowledge/workout_log.csv"))

if not API_KEY:
    print("❌ WGER_API_KEY secret not found.")
    exit(1)

BASE = "https://wger.de/api/v2"
HDRS = {"Authorization": f"Token {API_KEY}", "Accept": "application/json"}

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
                # Unexpected shape; treat as single page
                if isinstance(data, dict):
                    results.append(data)
                next_url = None
        except requests.exceptions.RequestException as e:
            print(f"Error fetching {next_url}: {e}")
            return None
    return results

def english_exercise_name(ex: dict) -> str:
    """Prefer English translation; fall back to base 'name' or ID."""
    trs = ex.get("translations") or []
    for t in trs:
        # English is language==2 on wger.de
        if t.get("language") == 2 and t.get("name"):
            return t["name"]
    # Fallbacks
    if ex.get("name"):
        return ex["name"]
    return f"Exercise {ex.get('id', '?')}"

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
    exercise_lookup = {}
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
    logs_url = f"{BASE}/workoutlog/?limit=200"
    all_logs = fetch_paginated_data(logs_url, headers)
    if all_logs is None:
        print("❌ Failed to fetch workout logs. Aborting.")
        exit(1)
    if not all_logs:
        print("No workout logs found on wger.")
        return

    # --- 3. Process logs into CSV rows ---
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    header = ["date", "exercise_name", "category", "reps", "weight_kg"]

    processed_rows = []
    for log in all_logs:
        # Common fields on wger workoutlog responses:
        # 'date', 'exercise' (id), 'repetitions' or 'reps', 'weight'
        ex_id = log.get("exercise")
        details = exercise_lookup.get(ex_id, {})
        name = details.get("name", f"Unknown ID: {ex_id}")
        cat = details.get("category", "N/A")

        reps = log.get("repetitions", log.get("reps"))
        wt = log.get("weight")
        processed_rows.append({
            "date": log.get("date") or log.get("created") or "",
            "exercise_name": name,
            "category": cat,
            "reps": reps if reps is not None else "",
            "weight_kg": wt if wt is not None else "",
        })

    # --- 4. Append deduped rows to CSV ---
    existing = set()
    if CSV_PATH.exists():
        with open(CSV_PATH, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing.add(tuple(row.get(k, "") for k in header))

    new_rows = []
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
    else:
        print("No new workout sets to add.")

    print("✅ Sync complete.")

if __name__ == "__main__":
    main()
