#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fetch the Wger exercise catalog and upsert it into the PostgreSQL database.
This script replaces the previous file-based caching mechanism.
"""
import sys
from typing import Any, Dict, List, Optional
import requests

# NOTE: Adjust this import path if your project structure is different.
# This path assumes a 'pete_e' source root.
from pete_e.infrastructure.postgres_dal import PostgresDal
from pete_e.config import get_env, settings

BASE = str(get_env("WGER_BASE_URL", default=settings.WGER_BASE_URL)).strip().rstrip("/")

def fetch_all(url: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Fetch all pages of results from a Wger API endpoint."""
    results: List[Dict[str, Any]] = []
    next_url = url
    while next_url:
        try:
            r = requests.get(next_url, params=params if next_url == url else None, timeout=60)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and "results" in data:
                results.extend(data["results"])
                next_url = data.get("next")
            elif isinstance(data, list):
                results.extend(data)
                next_url = None
            else:
                break
        except requests.RequestException as e:
            print(f"[ERROR] Failed to fetch data from {next_url}: {e}", file=sys.stderr)
            sys.exit(1)
    return results

def pick_english(translations: List[Dict[str, Any]]) -> Dict[str, str]:
    """Prefer English (language==2); fallback to any translation with a name."""
    name = ""
    desc = ""
    if not isinstance(translations, list):
        return {"name": "", "description": ""}
    en = next((t for t in translations if t.get("language") == 2 and t.get("name")), None)
    chosen = en or next((t for t in translations if t.get("name")), None)
    if chosen:
        name = chosen.get("name") or ""
        desc = (chosen.get("description") or "").strip()
    return {"name": name, "description": desc}

def update_exercises(dal: PostgresDal) -> int:
    """Fetch exercises and their relations, then upsert them into the database."""
    print(f"[wger] Fetching exercises from: {BASE}/exerciseinfo/")
    rows = fetch_all(f"{BASE}/exerciseinfo/", params={"limit": 200})

    processed_exercises: List[Dict[str, Any]] = []
    for ex in rows:
        eng = pick_english(ex.get("translations") or [])
        processed_exercises.append({
            "id": ex.get("id"),
            "uuid": ex.get("uuid"),
            "name": eng["name"],
            "description": eng["description"],
            "category_id": (ex.get("category") or {}).get("id"),
            "equipment_ids": [eq.get("id") for eq in ex.get("equipment", []) if eq.get("id")],
            "primary_muscle_ids": [m.get("id") for m in ex.get("muscles", []) if m.get("id")],
            "secondary_muscle_ids": [m.get("id") for m in ex.get("muscles_secondary", []) if m.get("id")],
        })

    if processed_exercises:
        print(f"[wger] Upserting {len(processed_exercises)} exercises into the database.")
        dal.upsert_wger_exercises(processed_exercises)
    return len(processed_exercises)

def update_catalog_item(dal: PostgresDal, endpoint: str, friendly_name: str, upsert_func) -> int:
    """Generic function to fetch a catalog endpoint and upsert its items."""
    print(f"[wger] Fetching {friendly_name} from: {BASE}/{endpoint}/")
    rows = fetch_all(f"{BASE}/{endpoint}/", params={"limit": 200})
    if rows:
        print(f"[wger] Upserting {len(rows)} {friendly_name} into the database.")
        upsert_func(rows)
    return len(rows)

def main() -> None:
    """
    Main function to run the catalog update process.
    Ensures the database connection pool is closed on exit.
    """
    try:
        total = 0
        print("[wger] Starting catalog database refresh...")
        with PostgresDal() as dal:
            # Order is important due to foreign key constraints.
            total += update_catalog_item(dal, "exercisecategory", "categories", dal.upsert_wger_categories)
            total += update_catalog_item(dal, "equipment", "equipment", dal.upsert_wger_equipment)
            total += update_catalog_item(dal, "muscle", "muscles", dal.upsert_wger_muscles)
            total += update_exercises(dal)

        print(f"[wger] Catalog refresh done. Total objects processed: {total}")

    except Exception as e:
        print(f"[ERROR] An unexpected error occurred during catalog refresh: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()

