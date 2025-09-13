import json
import os
import sys
from pathlib import Path

import psycopg

# This allows the script to import the settings from the pete_e module
# by adding the project root to the Python path.
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from pete_e.config import settings


def get_catalog_name_to_id_map(cursor, table_name: str) -> dict:
    """Queries a catalog table to create a mapping from item name to item ID."""
    cursor.execute(f'SELECT "name", id FROM {table_name};')
    return {name.lower(): id for name, id in cursor.fetchall()}


def migrate_wger_catalogs(conn):
    """
    Migrates the static Wger catalog data (categories, muscles, equipment, exercises)
    into the respective dimension tables. This must be run before migrating daily data.
    """
    print("--- Starting Wger Catalog Migration ---")
    
    with conn.cursor() as cur:
        # 1. Migrate Simple Catalogs (Categories, Equipment, Muscles)
        print("Migrating categories...")
        categories = json.loads((settings.WGER_CATALOG_PATH / "exercisecategory.json").read_text())
        for cat in categories:
            cur.execute(
                """
                INSERT INTO wger_category (id, "name") VALUES (%s, %s)
                ON CONFLICT (id) DO UPDATE SET "name" = EXCLUDED.name;
                """,
                (cat["id"], cat["name"]),
            )

        print("Migrating equipment...")
        equipment = json.loads((settings.WGER_CATALOG_PATH / "equipment.json").read_text())
        for item in equipment:
            cur.execute(
                """
                INSERT INTO wger_equipment (id, "name") VALUES (%s, %s)
                ON CONFLICT (id) DO UPDATE SET "name" = EXCLUDED.name;
                """,
                (item["id"], item["name"]),
            )

        print("Migrating muscles...")
        muscles = json.loads((settings.WGER_CATALOG_PATH / "muscles.json").read_text())
        for muscle in muscles:
            cur.execute(
                """
                INSERT INTO wger_muscle (id, "name", name_en, is_front) VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    "name" = EXCLUDED.name, name_en = EXCLUDED.name_en, is_front = EXCLUDED.is_front;
                """,
                (muscle["id"], muscle["name"], muscle["name_en"], muscle["is_front"]),
            )
        
        # Create maps for resolving names to IDs in the next step
        cat_map = get_catalog_name_to_id_map(cur, "wger_category")
        equip_map = get_catalog_name_to_id_map(cur, "wger_equipment")
        muscle_map = get_catalog_name_to_id_map(cur, "wger_muscle")

        # 2. Migrate Exercises and their Many-to-Many relationships
        print("Migrating exercises and relationships...")
        exercises = json.loads((settings.WGER_CATALOG_PATH / "exercises_en.json").read_text())
        for ex in exercises:
            category_id = cat_map.get(ex["category"].lower())
            cur.execute(
                """
                INSERT INTO wger_exercise (id, uuid, "name", description, category_id)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    uuid = EXCLUDED.uuid, "name" = EXCLUDED.name,
                    description = EXCLUDED.description, category_id = EXCLUDED.category_id;
                """,
                (ex["id"], ex["uuid"], ex["name"], ex.get("description_html", ""), category_id),
            )

            # Link equipment
            for item_name in ex.get("equipment", []):
                if equipment_id := equip_map.get(item_name.lower()):
                    cur.execute(
                        "INSERT INTO wger_exercise_equipment (exercise_id, equipment_id) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
                        (ex["id"], equipment_id),
                    )
            
            # Link primary muscles
            for muscle_name in ex.get("muscles_primary", []):
                if muscle_id := muscle_map.get(muscle_name.lower()):
                    cur.execute(
                        "INSERT INTO wger_exercise_muscle_primary (exercise_id, muscle_id) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
                        (ex["id"], muscle_id),
                    )

            # Link secondary muscles
            for muscle_name in ex.get("muscles_secondary", []):
                if muscle_id := muscle_map.get(muscle_name.lower()):
                    cur.execute(
                        "INSERT INTO wger_exercise_muscle_secondary (exercise_id, muscle_id) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
                        (ex["id"], muscle_id),
                    )

    print("--- Wger Catalog Migration Complete ---")


def migrate_daily_data(conn):
    """
    Iterates through all `knowledge/daily/*.json` files and migrates the data
    into the `daily_summary` and `strength_log` tables.
    """
    print("\n--- Starting Daily Data Migration ---")
    daily_files = sorted(settings.DAILY_KNOWLEDGE_PATH.glob("*.json"))

    if not daily_files:
        print("No daily files found to migrate.")
        return

    with conn.cursor() as cur:
        for file_path in daily_files:
            print(f"Processing {file_path.name}...")
            data = json.loads(file_path.read_text())

            # 1. Insert into daily_summary
            summary_date = data.get("date")
            if not summary_date:
                continue

            withings = data.get("withings", {})
            apple = data.get("apple", {})
            sleep = apple.get("sleep_minutes", {})

            cur.execute(
                """
                INSERT INTO daily_summary (
                    "date", weight_kg, body_fat_pct, steps, exercise_minutes,
                    calories_active, calories_resting, stand_minutes, distance_m,
                    hr_resting, hr_avg, hr_max, hr_min, sleep_asleep_minutes, sleep_details
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT ("date") DO UPDATE SET
                    weight_kg = EXCLUDED.weight_kg, body_fat_pct = EXCLUDED.body_fat_pct,
                    steps = EXCLUDED.steps, exercise_minutes = EXCLUDED.exercise_minutes,
                    calories_active = EXCLUDED.calories_active, calories_resting = EXCLUDED.calories_resting,
                    stand_minutes = EXCLUDED.stand_minutes, distance_m = EXCLUDED.distance_m,
                    hr_resting = EXCLUDED.hr_resting, hr_avg = EXCLUDED.hr_avg,
                    hr_max = EXCLUDED.hr_max, hr_min = EXCLUDED.hr_min,
                    sleep_asleep_minutes = EXCLUDED.sleep_asleep_minutes,
                    sleep_details = EXCLUDED.sleep_details;
                """,
                (
                    summary_date,
                    withings.get("weight_kg"),
                    withings.get("body_fat_pct"),
                    apple.get("steps"),
                    apple.get("exercise_minutes"),
                    apple.get("calories_active"),
                    apple.get("calories_resting"),
                    apple.get("stand_minutes"),
                    apple.get("distance_m"),
                    apple.get("hr_resting"),
                    apple.get("hr_avg"),
                    apple.get("hr_max"),
                    apple.get("hr_min"),
                    sleep.get("asleep"),
                    json.dumps(sleep) if sleep else None,
                ),
            )

            # 2. Insert into strength_log
            wger_logs = data.get("wger", [])
            for log in wger_logs:
                cur.execute(
                    """
                    INSERT INTO strength_log (
                        id, summary_date, exercise_id, reps, weight_kg, rir, wger_session_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        summary_date = EXCLUDED.summary_date, exercise_id = EXCLUDED.exercise_id,
                        reps = EXCLUDED.reps, weight_kg = EXCLUDED.weight_kg,
                        rir = EXCLUDED.rir, wger_session_id = EXCLUDED.wger_session_id;
                    """,
                    (
                        log.get("id"),
                        summary_date,
                        log.get("exercise_id"),
                        log.get("reps"),
                        log.get("weight"),
                        log.get("rir"),
                        log.get("session_id"),
                    ),
                )
    print("--- Daily Data Migration Complete ---")


def main():
    """Main function to orchestrate the migration process."""
    if not settings.DATABASE_URL:
        print("ERROR: DATABASE_URL is not set in your environment.", file=sys.stderr)
        sys.exit(1)

    try:
        # Use a single connection for the entire migration process
        with psycopg.connect(settings.DATABASE_URL) as conn:
            migrate_wger_catalogs(conn)
            migrate_daily_data(conn)
            # The 'with' block automatically commits the transaction on success
            print("\nMigration successful! All data has been committed to the database.")
    except psycopg.Error as e:
        print(f"\nDatabase error occurred: {e}", file=sys.stderr)
        print("Migration failed. The transaction has been rolled back.", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"\nFile not found: {e}", file=sys.stderr)
        print("Please ensure all Wger catalog and daily JSON files are in the correct 'knowledge' directory.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
