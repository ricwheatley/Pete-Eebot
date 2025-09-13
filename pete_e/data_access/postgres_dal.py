import json
from datetime import date
from typing import Any, Dict, List

import psycopg
from psycopg.rows import dict_row
from psycopg.pool import ConnectionPool

from pete_e.config import settings
from pete_e.data_access.dal import DataAccessLayer
from pete_e.infra import log_utils

# A connection pool is a standard practice for managing database connections.
# It's more efficient than opening and closing a new connection every time.
# We create a single global pool instance. The `min_size` and `max_size` are
# suitable for this single-threaded application.
pool = ConnectionPool(
    conninfo=settings.DATABASE_URL,
    min_size=1,
    max_size=3,
    # This tells psycopg to return rows as dictionary-like objects, which is
    # very convenient for converting to/from our application's data structures.
    row_factory=dict_row
)


class PostgresDal(DataAccessLayer):
    """
    A Data Access Layer implementation that uses a PostgreSQL database as the backend.
    This class fulfills the contract defined by the DataAccessLayer ABC.
    """

    def load_lift_log(self) -> Dict[str, Any]:
        """Loads the entire lift log from the strength_log table."""
        log_utils.log_message("[PostgresDal] Loading lift log")
        lift_log = {}
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT exercise_id, summary_date, reps, weight_kg, rir FROM strength_log ORDER BY summary_date ASC;")
                for row in cur.fetchall():
                    key = str(row["exercise_id"])
                    if key not in lift_log:
                        lift_log[key] = []
                    
                    lift_log[key].append({
                        "date": row["summary_date"].isoformat(),
                        "reps": row["reps"],
                        "weight": float(row["weight_kg"]),
                        "rir": float(row["rir"]) if row["rir"] is not None else None,
                    })
        return lift_log

    def save_lift_log(self, log: Dict[str, Any]) -> None:
        """
        Saves the entire lift log. This is a complex operation; in a relational
        database, we typically append entries rather than saving the whole log.
        This implementation will insert/update entries.
        """
        log_utils.log_message("[PostgresDal] Saving lift log")
        with pool.connection() as conn:
            with conn.cursor() as cur:
                for exercise_id, entries in log.items():
                    for entry in entries:
                        # This is a placeholder for a more complex upsert logic if needed.
                        # For now, we assume append_log_entry is the primary way to add data.
                        # This method is less critical in the new architecture.
                        pass
        log_utils.log_message("[PostgresDal] save_lift_log is a no-op in this implementation.", "WARN")


    def load_history(self) -> Dict[str, Any]:
        """
        Loads the consolidated history by querying the daily_summary table and
        reconstructing the nested JSON structure.
        """
        log_utils.log_message("[PostgresDal] Loading history")
        history = {}
        with pool.connection() as conn:
            with conn.cursor() as cur:
                # Query daily summaries
                cur.execute("SELECT * FROM daily_summary ORDER BY date ASC;")
                summaries = {row['date'].isoformat(): dict(row) for row in cur.fetchall()}

                # Query strength logs and group them by date
                cur.execute("SELECT * FROM strength_log ORDER BY summary_date ASC;")
                strength_logs = {}
                for row in cur.fetchall():
                    day = row['summary_date'].isoformat()
                    if day not in strength_logs:
                        strength_logs[day] = []
                    strength_logs[day].append({
                        "id": row["id"],
                        "exercise_id": row["exercise_id"],
                        "reps": row["reps"],
                        "weight": float(row["weight_kg"]),
                        "rir": float(row["rir"]) if row["rir"] is not None else None
                    })

                # Reconstruct the nested format
                for day, summary_data in summaries.items():
                    history[day] = {
                        "date": day,
                        "withings": {"weight_kg": summary_data.get("weight_kg"), "body_fat_pct": summary_data.get("body_fat_pct")},
                        "apple": {
                            "steps": summary_data.get("steps"),
                            "exercise_minutes": summary_data.get("exercise_minutes"),
                            "sleep_minutes": summary_data.get("sleep_details")
                        },
                        "wger": strength_logs.get(day, [])
                    }
        return history

    def save_history(self, history: Dict[str, Any]) -> None:
        """Saves the history. In the DB world, this is handled by saving daily summaries."""
        log_utils.log_message("[PostgresDal] Saving history via daily summaries")
        with pool.connection() as conn:
            for day, data in history.items():
                self.save_daily_summary(data, date.fromisoformat(day))
        log_utils.log_message("[PostgresDal] History save complete.")


    def save_daily_summary(self, summary: Dict[str, Any], day: date) -> None:
        """Saves a daily summary to the daily_summary table."""
        log_utils.log_message(f"[PostgresDal] Saving daily summary for {day.isoformat()}")
        withings = summary.get("withings", {})
        apple = summary.get("apple", {})
        sleep = apple.get("sleep_minutes", {})

        with pool.connection() as conn:
            with conn.cursor() as cur:
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
                        day.isoformat(),
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

    def load_body_age(self) -> Dict[str, Any]:
        """
        Body age is not stored in the database as it is calculated on the fly.
        This DAL method will return an empty dictionary to satisfy the contract.
        In a more advanced implementation, this could query and calculate an
        age delta based on historical data.
        """
        log_utils.log_message("[PostgresDal] load_body_age is a no-op.", "INFO")
        return {}
