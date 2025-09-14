"""
PostgreSQL implementation of the Data Access Layer.

This class handles all communication with the PostgreSQL database using a
robust connection pool for efficiency and reliability.
"""

from datetime import date
from typing import Any, Dict, List, Optional
import json

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
        """Upserts a row into ``daily_summary``."""
        log_utils.log_message(
            f"[PostgresDal] Saving daily summary for {day.isoformat()}", "INFO"
        )
        withings = summary.get("withings", {})
        apple = summary.get("apple", {})
        sleep = apple.get("sleep", {})

        try:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO daily_summary (
                            summary_date, weight_kg, body_fat_pct, muscle_mass_kg, water_pct,
                            steps, exercise_minutes, calories_active, calories_resting, stand_minutes,
                            distance_m, hr_resting, hr_avg, hr_max, hr_min,
                            sleep_total_minutes, sleep_asleep_minutes, sleep_rem_minutes,
                            sleep_deep_minutes, sleep_core_minutes, sleep_awake_minutes
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (summary_date) DO UPDATE SET
                            weight_kg = EXCLUDED.weight_kg,
                            body_fat_pct = EXCLUDED.body_fat_pct,
                            muscle_mass_kg = EXCLUDED.muscle_mass_kg,
                            water_pct = EXCLUDED.water_pct,
                            steps = EXCLUDED.steps,
                            exercise_minutes = EXCLUDED.exercise_minutes,
                            calories_active = EXCLUDED.calories_active,
                            calories_resting = EXCLUDED.calories_resting,
                            stand_minutes = EXCLUDED.stand_minutes,
                            distance_m = EXCLUDED.distance_m,
                            hr_resting = EXCLUDED.hr_resting,
                            hr_avg = EXCLUDED.hr_avg,
                            hr_max = EXCLUDED.hr_max,
                            hr_min = EXCLUDED.hr_min,
                            sleep_total_minutes = EXCLUDED.sleep_total_minutes,
                            sleep_asleep_minutes = EXCLUDED.sleep_asleep_minutes,
                            sleep_rem_minutes = EXCLUDED.sleep_rem_minutes,
                            sleep_deep_minutes = EXCLUDED.sleep_deep_minutes,
                            sleep_core_minutes = EXCLUDED.sleep_core_minutes,
                            sleep_awake_minutes = EXCLUDED.sleep_awake_minutes;
                        """,
                        (
                            day,
                            withings.get("weight"),
                            withings.get("fat_percent"),
                            withings.get("muscle_mass"),
                            withings.get("water_percent"),
                            apple.get("steps"),
                            apple.get("exercise_minutes"),
                            apple.get("calories", {}).get("active"),
                            apple.get("calories", {}).get("resting"),
                            apple.get("stand_minutes"),
                            apple.get("distance_m"),
                            apple.get("heart_rate", {}).get("resting"),
                            apple.get("heart_rate", {}).get("avg"),
                            apple.get("heart_rate", {}).get("max"),
                            apple.get("heart_rate", {}).get("min"),
                            sleep.get("in_bed"),
                            sleep.get("asleep"),
                            sleep.get("rem"),
                            sleep.get("deep"),
                            sleep.get("core"),
                            sleep.get("awake"),
                        ),
                    )
        except Exception as e:
            log_utils.log_message(
                f"Error saving daily summary to Postgres for {day}: {e}", "ERROR"
            )

    def save_strength_log_entry(
        self,
        exercise_id: int,
        log_date: date,
        set_number: int,
        reps: int,
        weight_kg: float,
        rir: Optional[float] = None,
    ) -> None:
        """Insert a single set into ``strength_log`` with set ordering.

        Uniqueness enforced by (summary_date, exercise_id, set_number).
        """
        try:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO strength_log (
                            summary_date, exercise_id, set_number, reps, weight_kg, rir
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (summary_date, exercise_id, set_number)
                        DO UPDATE SET
                            reps = EXCLUDED.reps,
                            weight_kg = EXCLUDED.weight_kg,
                            rir = EXCLUDED.rir;
                        """,
                        (log_date, exercise_id, set_number, reps, weight_kg, rir),
                    )
        except Exception as e:
            log_utils.log_message(
                f"Error saving strength log entry for {log_date}: {e}", "ERROR"
            )


    def load_history(self) -> Dict[str, Any]:
        """Return all rows from ``daily_summary`` keyed by ISO date."""
        out: Dict[str, Any] = {}
        try:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM daily_summary ORDER BY summary_date ASC;"
                    )
                    for row in cur.fetchall():
                        day = row["summary_date"].isoformat()
                        out[day] = {
                            "withings": {
                                "weight": float(row["weight_kg"])
                                if row["weight_kg"] is not None
                                else None,
                                "fat_percent": float(row["body_fat_pct"])
                                if row["body_fat_pct"] is not None
                                else None,
                                "muscle_mass": float(row["muscle_mass_kg"])
                                if row["muscle_mass_kg"] is not None
                                else None,
                                "water_percent": float(row["water_pct"])
                                if row["water_pct"] is not None
                                else None,
                            },
                            "apple": {
                                "steps": row["steps"],
                                "exercise_minutes": row["exercise_minutes"],
                                "calories": {
                                    "active": row["calories_active"],
                                    "resting": row["calories_resting"],
                                },
                                "stand_minutes": row["stand_minutes"],
                                "distance_m": row["distance_m"],
                                "heart_rate": {
                                    "resting": row["hr_resting"],
                                    "avg": row["hr_avg"],
                                    "max": row["hr_max"],
                                    "min": row["hr_min"],
                                },
                                "sleep": {
                                    "in_bed": row["sleep_total_minutes"],
                                    "asleep": row["sleep_asleep_minutes"],
                                    "rem": row["sleep_rem_minutes"],
                                    "deep": row["sleep_deep_minutes"],
                                    "core": row["sleep_core_minutes"],
                                    "awake": row["sleep_awake_minutes"],
                                },
                            },
                        }
        except Exception as e:
            log_utils.log_message(
                f"Error loading daily history from Postgres: {e}", "ERROR"
            )
        return out

    def save_history(self, history: Dict[str, Any]) -> None:
        """Persist provided history by upserting each summary."""
        for day_str, data in history.items():
            try:
                self.save_daily_summary(data, date.fromisoformat(day_str))
            except Exception as e:
                log_utils.log_message(
                    f"Error saving history for {day_str}: {e}", "ERROR"
                )

    def _row_to_summary(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "withings": {
                "weight": float(row["weight_kg"]) if row["weight_kg"] is not None else None,
                "fat_percent": float(row["body_fat_pct"]) if row["body_fat_pct"] is not None else None,
                "muscle_mass": float(row["muscle_mass_kg"]) if row["muscle_mass_kg"] is not None else None,
                "water_percent": float(row["water_pct"]) if row["water_pct"] is not None else None,
            },
            "apple": {
                "steps": row["steps"],
                "exercise_minutes": row["exercise_minutes"],
                "calories": {
                    "active": row["calories_active"],
                    "resting": row["calories_resting"],
                },
                "stand_minutes": row["stand_minutes"],
                "distance_m": row["distance_m"],
                "heart_rate": {
                    "resting": row["hr_resting"],
                    "avg": row["hr_avg"],
                    "max": row["hr_max"],
                    "min": row["hr_min"],
                },
                "sleep": {
                    "in_bed": row["sleep_total_minutes"],
                    "asleep": row["sleep_asleep_minutes"],
                    "rem": row["sleep_rem_minutes"],
                    "deep": row["sleep_deep_minutes"],
                    "core": row["sleep_core_minutes"],
                    "awake": row["sleep_awake_minutes"],
                },
            },
        }

    def save_body_age(self, result: Dict[str, Any]) -> None:
        """Upsert a flattened body age record into body_age_log."""
        try:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO body_age_log (
                            summary_date, input_window_days,
                            crf, body_comp, activity, recovery,
                            composite, body_age_years, delta_years,
                            used_vo2max_direct, cap_minus_10_applied
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (summary_date) DO UPDATE SET
                            input_window_days = EXCLUDED.input_window_days,
                            crf = EXCLUDED.crf,
                            body_comp = EXCLUDED.body_comp,
                            activity = EXCLUDED.activity,
                            recovery = EXCLUDED.recovery,
                            composite = EXCLUDED.composite,
                            body_age_years = EXCLUDED.body_age_years,
                            delta_years = EXCLUDED.delta_years,
                            used_vo2max_direct = EXCLUDED.used_vo2max_direct,
                            cap_minus_10_applied = EXCLUDED.cap_minus_10_applied;
                        """,
                        (
                            date.fromisoformat(result["date"]),
                            result.get("input_window_days"),
                            result.get("subscores", {}).get("crf"),
                            result.get("subscores", {}).get("body_comp"),
                            result.get("subscores", {}).get("activity"),
                            result.get("subscores", {}).get("recovery"),
                            result.get("composite"),
                            result.get("body_age_years"),
                            result.get("age_delta_years"),
                            result.get("assumptions", {}).get("used_vo2max_direct"),
                            result.get("assumptions", {}).get("cap_minus_10_applied"),
                        ),
                    )
        except Exception as e:
            log_utils.log_message(
                f"Error saving body age result for {result.get('date')}: {e}", "ERROR"
            )

    def load_body_age(self) -> Dict[str, Any]:
        """Load all flattened body age records keyed by ISO date."""
        out: Dict[str, Any] = {}
        try:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT
                            summary_date, input_window_days,
                            crf, body_comp, activity, recovery,
                            composite, body_age_years, delta_years,
                            used_vo2max_direct, cap_minus_10_applied
                        FROM body_age_log
                        ORDER BY summary_date ASC;
                        """
                    )
                    for row in cur.fetchall():
                        out[row["summary_date"].isoformat()] = {
                            "input_window_days": row["input_window_days"],
                            "subscores": {
                                "crf": float(row["crf"]) if row["crf"] is not None else None,
                                "body_comp": float(row["body_comp"]) if row["body_comp"] is not None else None,
                                "activity": float(row["activity"]) if row["activity"] is not None else None,
                                "recovery": float(row["recovery"]) if row["recovery"] is not None else None,
                            },
                            "composite": float(row["composite"]) if row["composite"] is not None else None,
                            "body_age_years": float(row["body_age_years"]) if row["body_age_years"] is not None else None,
                            "age_delta_years": float(row["delta_years"]) if row["delta_years"] is not None else None,
                            "assumptions": {
                                "used_vo2max_direct": row["used_vo2max_direct"],
                                "cap_minus_10_applied": row["cap_minus_10_applied"],
                            },
                        }
        except Exception as e:
            log_utils.log_message(f"Error loading body age from Postgres: {e}", "ERROR")
        return out

    def get_historical_metrics(self, days: int) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        try:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM daily_summary ORDER BY summary_date DESC LIMIT %s;",
                        (days,),
                    )
                    rows = cur.fetchall()
                    for row in reversed(rows):
                        out.append(self._row_to_summary(row))
        except Exception as e:
            log_utils.log_message(
                f"Error loading historical metrics for last {days} days: {e}", "ERROR"
            )
        return out

    def get_daily_summary(self, target_date: date) -> Optional[Dict[str, Any]]:
        try:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM daily_summary WHERE summary_date = %s;",
                        (target_date,),
                    )
                    row = cur.fetchone()
                    if row:
                        return self._row_to_summary(row)
        except Exception as e:
            log_utils.log_message(
                f"Error loading daily summary for {target_date}: {e}", "ERROR"
            )
        return None

    def get_historical_data(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        try:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT * FROM daily_summary
                        WHERE summary_date BETWEEN %s AND %s
                        ORDER BY summary_date ASC;
                        """,
                        (start_date, end_date),
                    )
                    for row in cur.fetchall():
                        out.append(self._row_to_summary(row))
        except Exception as e:
            log_utils.log_message(
                f"Error loading historical data between {start_date} and {end_date}: {e}",
                "ERROR",
            )
        return out

    def save_training_plan(self, plan: dict, start_date: date) -> None:
        """Upsert a training plan into the training_plans table."""
        log_utils.log_message(
            f"[PostgresDal] Saving training plan for {start_date.isoformat()}", "INFO"
        )
        try:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO training_plans (start_date, plan)
                        VALUES (%s, %s)
                        ON CONFLICT (start_date) DO UPDATE SET plan = EXCLUDED.plan;
                        """,
                        (start_date, json.dumps(plan)),
                    )
        except Exception as e:
            log_utils.log_message(
                f"Error saving training plan for {start_date}: {e}", "ERROR"
            )

    def save_validation_log(self, tag: str, adjustments: List[str]) -> None:
        """Persist validation logs via log utils (DB currently not used)."""
        log_utils.log_message(f"{tag}: {adjustments}", "INFO")
