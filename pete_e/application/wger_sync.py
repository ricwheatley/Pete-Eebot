#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fetch the Wger exercise catalog and upsert it into the PostgreSQL database.
Also seeds the main lifts and assistance pools after the catalog is refreshed.
"""
import sys
from typing import Any, Dict, List

from pete_e.infrastructure.postgres_dal import PostgresDal
from pete_e.infrastructure.wger_client import WgerClient
from pete_e.infrastructure.wger_seeder import WgerSeeder
from pete_e.infrastructure.wger_writer import WgerWriter

from pete_e.infrastructure import log_utils
from pete_e.domain import schedule_rules

# British English comments and docstrings.

STANDARD_EQUIPMENT_NAMES = {
    "barbell",
    "bench",
    "body weight",
    "bodyweight",
    "dumbbell",
    "gym mat",
    "mat",
    "none",
    "pull-up bar",
}


def _equipment_name_map(equipment: List[Dict[str, Any]]) -> Dict[int, str]:
    return {int(item["id"]): str(item.get("name") or "").strip().lower() for item in equipment if item.get("id") is not None}


def _has_only_standard_equipment(exercise: Dict[str, Any], equipment_names: Dict[int, str]) -> bool:
    exercise_equipment = exercise.get("equipment") or []
    if not exercise_equipment:
        return True
    names = [equipment_names.get(int(eq["id"]), "") for eq in exercise_equipment if eq.get("id") is not None]
    return bool(names) and all(name in STANDARD_EQUIPMENT_NAMES for name in names)


def _pick_english_translation(translations: List[Dict[str, Any]]) -> Dict[str, str]:
    """Return the English translation only; exercises without one are excluded."""
    if not isinstance(translations, list):
        return {"name": "", "description": ""}

    chosen = next((t for t in translations if t.get("language") == 2 and t.get("name")), None)

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

    dal = PostgresDal()
    try:
        with dal.connection() as conn:
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

            equipment_names = _equipment_name_map(equipment)
            protected_ids = set(schedule_rules.MAIN_LIFT_IDS) | {schedule_rules.BLAZE_ID, schedule_rules.TREADMILL_RUN_ID, schedule_rules.OUTDOOR_RUN_ID}
            processed_exercises: List[Dict[str, Any]] = []
            for ex in exercises_raw:
                eng = _pick_english_translation(ex.get("translations") or [])
                exercise_id = ex.get("id")
                if not eng["name"] and exercise_id not in protected_ids:
                    continue
                if exercise_id not in protected_ids and not _has_only_standard_equipment(ex, equipment_names):
                    continue
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
    finally:
        dal.close()

    log_utils.info("WGER catalogue refresh completed successfully.")


if __name__ == "__main__":
    try:
        run_wger_catalog_refresh()
    except (IOError, ValueError) as e:
        log_utils.error(f"Catalogue refresh failed: {e}")
        sys.exit(1)

