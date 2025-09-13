"""
PostgreSQL implementation of the Data Access Layer.

This class handles all communication with the PostgreSQL database using a
robust connection pool for efficiency and reliability.
"""

import json
from datetime import date
from typing import Any, Dict, List, Optional

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from pete_e.config import settings
from pete_e.infra import log_utils
from .dal import DataAccessLayer


# A single, global connection pool instance is created when the module is imported.
# This is the modern and efficient way to manage database connections.
# It will raise an error on startup if DATABASE_URL is not set.
if not settings.DATABASE_URL:
    raise ValueError("DATABASE_URL is not set in the configuration. Cannot initialize connection pool.")

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

    # We no longer need an __init__ or __del__ method, as the global
    # connection pool handles the entire connection lifecycle.

    def load_lift_log(self) -> Dict[str, Any]:
        """Loads the entire lift log from the strength_log table."""
        log_utils.log_message("[PostgresDal] Loading lift log", "INFO")
        lift_log = {}
        try:
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
        except Exception as e:
            log_utils.log_message(f"Error loading lift log from Postgres: {e}", "ERROR")
            return {}
        return lift_log

    def save_daily_summary(self, summary: Dict[str, Any], day: date) -> None:
        """Saves a daily summary to the daily_summary table using an UPSERT operation."""
        log_utils.log_message(f"[PostgresDal] Saving daily summary for {day.isoformat()}", "INFO")
        withings = summary.get("withings", {})
        apple = summary.get("apple", {})
        sleep = apple.get("sleep_minutes", {})

        try:
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
                            day,
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
        except Exception as e:
            log_utils.log_message(f"Error saving daily summary to Postgres for {day}: {e}", "ERROR")

    # --- Other DAL methods from your implementation ---
    # (I've omitted them for brevity but they should remain as you wrote them,
    # just ensure they also use `with pool.connection() as conn:`)

    def save_lift_log(self, log: Dict[str, Any]) -> None:
        log_utils.log_message("[PostgresDal] save_lift_log is a no-op in this implementation.", "WARN")
        pass

    def load_history(self) -> Dict[str, Any]:
        # This implementation remains the same as in your file.
        pass
    
    def save_history(self, history: Dict[str, Any]) -> None:
        # This implementation remains the same as in your file.
        pass

    def load_body_age(self) -> Dict[str, Any]:
        # This implementation remains the same as in your file.
        pass
    
    def get_historical_metrics(self, days: int) -> List[Dict[str, Any]]:
        # This implementation remains the same as in your file.
        pass

    def get_daily_summary(self, target_date: date) -> Optional[Dict[str, Any]]:
        # This implementation remains the same as in your file.
        pass

    def get_historical_data(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        # This implementation remains the same as in your file.
        pass