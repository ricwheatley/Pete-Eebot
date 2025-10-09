#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fetch the Wger exercise catalog and upsert it into the PostgreSQL database.
Also seeds the main lifts and assistance pools after the catalog is refreshed.
"""
import sys
from typing import Any, Dict, List

from pete_e.infrastructure.database import get_conn
from pete_e.infrastructure.wger_client import WgerClient
from pete_e.infrastructure.wger_seeder import WgerSeeder
from pete_e.infrastructure.wger_writer import WgerWriter

from pete_e.infrastructure import log_utils

# British English comments and docstrings.


def _pick_english_translation(translations: List[Dict[str, Any]]) -> Dict[str, str]:
    """Prefers English (language ID 2); falls back to any available translation."""
    if not isinstance(translations, list):
        return {"name": "", "description": ""}

    english_translation = next((t for t in translations if t.get("language") == 2 and t.get("name")), None)
    chosen = english_translation or next((t for t in translations if t.get("name")), None)
    
    if chosen:
        return {
            "name": chosen.get("name") or "",
            "description": (chosen.get("description") or "").strip()
        }
    return {"name": "", "description": ""}


def run_wger_catalog_refresh():
    """
    Orchestrates the end-to-end process of refreshing the WGER catalogue.
    Fetches all data from the WGER API and bulk-upserts it into the database.
    """
    log_utils.info("Starting WGER catalogue refresh...")

    wger_client = WgerClient()

    with get_conn() as conn:
        writer = WgerWriter(conn)

        # 1. Fetch and upsert reference data
        categories = wger_client.get_all_pages("/exercisecategory/", params={"limit": 200})
        writer.upsert_categories(categories)

        equipment = wger_client.get_all_pages("/equipment/", params={"limit": 200})
        writer.upsert_equipment(equipment)

        muscles = wger_client.get_all_pages("/muscle/", params={"limit": 200})
        writer.upsert_muscles(muscles)

        # 2. Fetch, process, and upsert exercises
        exercises_raw = wger_client.get_all_pages("/exerciseinfo/", params={"limit": 200})
        
        processed_exercises: List[Dict[str, Any]] = []
        for ex in exercises_raw:
            eng = _pick_english_translation(ex.get("translations") or [])
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
        
        writer.upsert_exercises(processed_exercises)

        # 3. Seed the main lifts and assistance pools
        seeder = WgerSeeder(conn)
        seeder.seed_main_lifts_and_assistance_pools()

        conn.commit()
    
    log_utils.info("WGER catalogue refresh completed successfully.")


if __name__ == "__main__":
    try:
        run_wger_catalog_refresh()
    except (IOError, ValueError) as e:
        log_utils.error(f"Catalogue refresh failed: {e}")
        sys.exit(1)

