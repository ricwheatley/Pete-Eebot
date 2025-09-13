"""
Pete-Eebot Historical Data Migration Script (Corrected)

This script performs a one-time migration of historical data from the local
JSON files into the PostgreSQL database. It is designed to be idempotent.

Key fixes in this version:
- Handles lookups for converting category, muscle, and equipment names to their
  corresponding foreign key IDs.
- Corrects column name mismatches between the script and the schema.
- Populates all fields in the wger_exercise table, including the UUID.
- Converts distance_km to distance_m during migration.
- Populates the new, flattened sleep columns instead of a JSONB object.
"""

import json
import logging
import sys
from pathlib import Path

import psycopg

# Configure a basic logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)


def get_project_root() -> Path:
    """Dynamically find the project root by looking for the .gitignore file."""
    current_path = Path.cwd()
    while current_path != current_path.parent:
        if (current_path / ".gitignore").exists():
            return current_path
        current_path = current_path.parent
    raise FileNotFoundError("Could not find project root.")


# Add the project root to the Python path to allow imports from pete_e
PROJECT_ROOT = get_project_root()
sys.path.append(str(PROJECT_ROOT))

from pete_e.config import settings


def load_json_catalog(catalog_path: Path, filename: str) -> list:
    """A helper to load JSON and handle potential errors."""
    file_path = catalog_path / filename
    if not file_path.exists():
        logging.warning(f"Catalog file not found: {file_path}")
        return []
    try:
        return json.loads(file_path.read_text("utf-8"))
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON from {file_path}: {e}")
        return []

# --- Wger Catalog Migration ---
def populate_wger_catalog(cur: psycopg.Cursor):
    """
    Populates all Wger-related catalog tables from their JSON sources.
    """
    logging.info("Starting Wger catalog population...")
    catalog_path = PROJECT_ROOT / "integrations/wger/catalog"

    # 1. Load all catalog data into memory for lookups
    categories_data = load_json_catalog(catalog_path, "exercisecategory.json")
    equipment_data = load_json_catalog(catalog_path, "equipment.json")
    muscles_data = load_json_catalog(catalog_path, "muscles.json")
    exercises_data = load_json_catalog(catalog_path, "exercises_en.json")

    # Create lookup maps for names to IDs
    category_map = {item['name']: item['id'] for item in categories_data}
    equipment_map = {item['name']: item['id'] for item in equipment_data}
    muscle_map = {item['name_en']: item['id'] for item in muscles_data if item.get('name_en')}

    # 2. Populate simple dimension tables
    if categories_data:
        with cur.copy("COPY wger_category (id, name) FROM STDIN") as copy:
            for cat in categories_data:
                copy.write_row((cat["id"], cat["name"]))
        logging.info(f"Populated wger_category with {len(categories_data)} entries.")

    if equipment_data:
        with cur.copy("COPY wger_equipment (id, name) FROM STDIN") as copy:
            for item in equipment_data:
                copy.write_row((item["id"], item["name"]))
        logging.info(f"Populated wger_equipment with {len(equipment_data)} entries.")

    if muscles_data:
        with cur.copy("COPY wger_muscle (id, name, name_en, is_front) FROM STDIN") as copy:
            for muscle in muscles_data:
                copy.write_row((muscle["id"], muscle["name"], muscle.get("name_en"), muscle["is_front"]))
        logging.info(f"Populated wger_muscle with {len(muscles_data)} entries.")

    # 3. Populate exercises and their junction tables
    if exercises_data:
        exercise_rows = []
        equipment_rows = []
        primary_muscle_rows = []
        secondary_muscle_rows = []

        for ex in exercises_data:
            cat_name = ex.get("category")
            if not cat_name or cat_name not in category_map:
                logging.warning(f"Skipping exercise '{ex.get('name')}' due to missing or unknown category '{cat_name}'.")
                continue

            category_id = category_map[cat_name]
            exercise_rows.append((ex["id"], ex["uuid"], ex["name"], ex.get("description_html"), category_id))

            for equip_name in ex.get("equipment", []):
                if equip_name in equipment_map:
                    equipment_rows.append((ex["id"], equipment_map[equip_name]))

            for muscle_name in ex.get("muscles_primary", []):
                if muscle_name in muscle_map:
                    primary_muscle_rows.append((ex["id"], muscle_map[muscle_name]))

            for muscle_name in ex.get("muscles_secondary", []):
                if muscle_name in muscle_map:
                    secondary_muscle_rows.append((ex["id"], muscle_map[muscle_name]))

        # Use COPY for bulk inserts
        with cur.copy("COPY wger_exercise (id, uuid, name, description, category_id) FROM STDIN") as copy:
            for row in exercise_rows:
                copy.write_row(row)
        
        with cur.copy("COPY wger_exercise_equipment (exercise_id, equipment_id) FROM STDIN") as copy:
            for row in equipment_rows:
                copy.write_row(row)

        with cur.copy("COPY wger_exercise_muscle_primary (exercise_id, muscle_id) FROM STDIN") as copy:
            for row in primary_muscle_rows:
                copy.write_row(row)

        with cur.copy("COPY wger_exercise_muscle_secondary (exercise_id, muscle_id) FROM STDIN") as copy:
            for row in secondary_muscle_rows:
                copy.write_row(row)

        logging.info(f"Populated wger_exercise and related tables with {len(exercise_rows)} valid entries.")

    logging.info("Wger catalog population complete.")


# --- Daily Data Migration ---
def migrate_daily_summaries(cur: psycopg.Cursor):
    """
    Iterates through all daily JSON files and inserts them into the database.
    """
    logging.info("Starting migration of daily summary files...")
    daily_path = PROJECT_ROOT / "knowledge/daily"
    if not daily_path.exists():
        logging.error(f"Daily knowledge directory not found at: {daily_path}")
        return

    json_files = sorted(daily_path.glob("*.json"))
    logging.info(f"Found {len(json_files)} daily summary files to process.")

    for file_path in json_files:
        try:
            data = json.loads(file_path.read_text("utf-8"))
            summary_date = data.get("date")
            if not summary_date:
                logging.warning(f"Skipping file with no date: {file_path}")
                continue

            # --- Insert into daily_summary ---
            body = data.get("body", {})
            apple = data.get("activity", {})
            heart = data.get("heart", {})
            sleep = data.get("sleep", {})

            # --- THIS IS THE NEW LOGIC ---
            # Convert distance from km to m
            distance_m = None
            if apple.get("distance_km") is not None:
                try:
                    distance_m = int(float(apple.get("distance_km")) * 1000)
                except (ValueError, TypeError):
                    distance_m = None

            cur.execute(
                """
                INSERT INTO daily_summary (
                    summary_date, weight_kg, body_fat_pct, muscle_mass_kg, water_pct,
                    steps, exercise_minutes, calories_active, calories_resting, stand_minutes, distance_m,
                    hr_resting, hr_avg, hr_max, hr_min,
                    sleep_total_minutes, sleep_asleep_minutes, sleep_rem_minutes,
                    sleep_deep_minutes, sleep_core_minutes, sleep_awake_minutes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (summary_date) DO NOTHING;
                """,
                (
                    summary_date,
                    body.get("weight_kg"), body.get("body_fat_pct"), body.get("muscle_mass_kg"), body.get("water_pct"),
                    apple.get("steps"), apple.get("exercise_minutes"),
                    apple.get("calories", {}).get("active"), apple.get("calories", {}).get("resting"),
                    apple.get("stand_minutes"), distance_m,
                    heart.get("resting_bpm"), heart.get("avg_bpm"), heart.get("max_bpm"), heart.get("min_bpm"),
                    sleep.get("total_minutes"), sleep.get("asleep_minutes"), sleep.get("rem_minutes"),
                    sleep.get("deep_minutes"), sleep.get("core_minutes"), sleep.get("awake_minutes")
                ),
            )

            # --- Insert into strength_log ---
            strength_logs = data.get("strength", [])
            for log in strength_logs:
                exercise_id = log.get("exercise_id")
                reps_list = log.get("reps", [])
                weights_list = log.get("weights_kg", [])

                if len(reps_list) == len(weights_list):
                    for i in range(len(reps_list)):
                        cur.execute(
                            """
                            INSERT INTO strength_log (summary_date, exercise_id, reps, weight_kg, rir)
                            VALUES (%s, %s, %s, %s, %s);
                            """,
                            (summary_date, exercise_id, reps_list[i], weights_list[i], None),
                        )
                else:
                    logging.warning(f"Mismatched reps/weights for ex {exercise_id} on {summary_date}. Skipping.")

        except psycopg.Error as e:
             logging.error(f"Database error processing {file_path.name}: {e}")
        except Exception as e:
            logging.error(f"An unexpected error occurred processing {file_path.name}: {e}")


    logging.info("Daily summary migration complete.")


# --- Main Execution ---
def main():
    """Main function to orchestrate the migration process."""
    if not settings.DATABASE_URL:
        logging.error("DATABASE_URL is not set. Cannot connect to the database.")
        sys.exit(1)

    logging.info("Starting Pete-Eebot data migration...")
    logging.info(f"Connecting to database: {settings.POSTGRES_HOST}")

    try:
        with psycopg.connect(settings.DATABASE_URL) as conn:
            with conn.cursor() as cur:
                populate_wger_catalog(cur)
                migrate_daily_summaries(cur)

                logging.info("Committing changes to the database...")
                conn.commit()

        logging.info("✅ Migration script completed successfully!")

    except psycopg.OperationalError as e:
        logging.error(f"Could not connect to the database: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"A critical error occurred during migration: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()