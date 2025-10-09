#!/usr/bin/env python3
# scripts/sync_wger_catalog.py
"""
Refreshes the local wger exercise catalog from the wger API
and seeds the main lift / assistance pool data.
"""
from pete_e.domain import schedule_rules # For MAIN_LIFT_IDS
from pete_e.infrastructure.postgres_dal import PostgresDal
from pete_e.infrastructure.wger_client import WgerClient
from pete_e.infrastructure import log_utils

def main():
    """Orchestrates the end-to-end catalog refresh."""
    log_utils.info("Starting WGER catalogue refresh...")
    dal = PostgresDal()
    client = WgerClient()

    try:
        # 1. Fetch catalog data from the API
        categories = client.get_all_pages("/exercisecategory/")
        equipment = client.get_all_pages("/equipment/")
        muscles = client.get_all_pages("/muscle/")
        exercises_raw = client.get_all_pages("/exerciseinfo/")

        # 2. Process exercises to match the DAL's expected format
        processed_exercises = []
        for ex in exercises_raw:
            translations = ex.get("translations") or []
            en_trans = next((t for t in translations if t.get("language") == 2), None) or {}
            processed_exercises.append({
                "id": ex.get("id"), "uuid": ex.get("uuid"),
                "name": en_trans.get("name", "Unknown"),
                "description": en_trans.get("description", ""),
                "category_id": (ex.get("category") or {}).get("id"),
                "equipment_ids": [eq.get("id") for eq in ex.get("equipment", []) if eq.get("id")],
                "primary_muscle_ids": [m.get("id") for m in ex.get("muscles", []) if m.get("id")],
                "secondary_muscle_ids": [m.get("id") for m in ex.get("muscles_secondary", []) if m.get("id")],
            })

        # 3. Use the DAL to bulk-upsert everything
        dal.upsert_wger_categories(categories)
        dal.upsert_wger_equipment(equipment)
        dal.upsert_wger_muscles(muscles)
        dal.upsert_wger_exercises_and_relations(processed_exercises)

        # 4. Use the DAL to seed relationships
        # (Assuming ASSISTANCE_POOL_DATA is defined in schedule_rules)
        dal.seed_main_lifts_and_assistance(
             main_lift_ids=schedule_rules.MAIN_LIFT_IDS,
             assistance_pool_data=schedule_rules.ASSISTANCE_POOL_DATA
        )
        
        log_utils.info("WGER catalogue refresh completed successfully.")

    except Exception as e:
        log_utils.error(f"Catalogue refresh failed: {e}", exc_info=True)
        raise
    finally:
        dal.close()

if __name__ == "__main__":
    main()