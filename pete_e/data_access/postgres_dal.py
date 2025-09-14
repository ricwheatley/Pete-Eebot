"""
PostgreSQL implementation of the Data Access Layer.

This class handles all communication with the PostgreSQL database using a
robust connection pool for efficiency and reliability.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional
import json

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from pete_e.config import settings
from pete_e.infra import log_utils
from pete_e.core import body_age
from .dal import DataAccessLayer


# -------------------------------------------------------------------------
# Connection Pool (with recycling + logging)
# -------------------------------------------------------------------------
if not settings.DATABASE_URL:
    raise ValueError("DATABASE_URL is not set in the configuration. Cannot initialize connection pool.")

try:
    _pool = ConnectionPool(
        conninfo=settings.DATABASE_URL,
        min_size=1,
        max_size=3,
        max_lifetime=60,   # recycle connections every 60s
        timeout=10,        # fail fast if DB not reachable
    )
    log_utils.log_message("[PostgresDal] Connection pool initialized", "INFO")
except Exception as e:
    log_utils.log_message(f"[PostgresDal] Failed to initialize connection pool: {e}", "ERROR")
    raise


class DictConn:
    """
    Wrapper around a pooled connection that ensures every cursor
    automatically uses dict_row.
    """
    def __init__(self, pool: ConnectionPool):
        self._pool = pool
        self._conn = None

    def __enter__(self):
        self._conn = self._pool.connection().__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self._conn.__exit__(exc_type, exc_val, exc_tb)

    def cursor(self):
        if not self._conn:
            raise RuntimeError("Connection not open")
        return self._conn.cursor(row_factory=dict_row)


def get_conn() -> DictConn:
    """
    Get a pooled connection with dict_row as default cursor output.
    Ensures the connection is alive before returning it.
    """
    conn = DictConn(_pool)
    try:
        # Sanity check the connection immediately
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
            cur.fetchone()
    except Exception as e:
        log_utils.log_message(f"[PostgresDal] Bad connection detected: {e}", "WARN")
        # Force reconnect by re-opening the pool connection
        conn = DictConn(_pool)
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
            cur.fetchone()
    return conn



# -------------------------------------------------------------------------
# Postgres DAL
# -------------------------------------------------------------------------
class PostgresDal(DataAccessLayer):
    """
    A Data Access Layer implementation that uses a PostgreSQL database as the backend.
    """

    # -------------------------------------------------------------------------
    # Strength log
    # -------------------------------------------------------------------------
    def load_lift_log(self) -> Dict[str, Any]:
        """Loads the entire lift log from the strength_log table, grouped by exercise_id."""
        log_utils.log_message("[PostgresDal] Loading lift log", "INFO")
        lift_log: Dict[str, List[Dict[str, Any]]] = {}
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT exercise_id, summary_date, set_number, reps, weight_kg, rir
                        FROM strength_log
                        ORDER BY summary_date ASC, exercise_id ASC, set_number ASC;
                        """
                    )
                    for row in cur.fetchall():
                        key = str(row["exercise_id"])
                        lift_log.setdefault(key, []).append({
                            "date": row["summary_date"].isoformat(),
                            "set_number": row["set_number"],
                            "reps": row["reps"],
                            "weight": float(row["weight_kg"]) if row["weight_kg"] is not None else None,
                            "rir": float(row["rir"]) if row["rir"] is not None else None,
                        })
        except Exception as e:
            log_utils.log_message(f"Error loading lift log from Postgres: {e}", "ERROR")
        return lift_log

    def save_lift_log(self, log: Dict[str, Any]) -> None:
        """
        Save a full lift log (exercise_id -> list of sets).

        Iterates through each exercise and its sets, and persists them using
        save_strength_log_entry. The set_number ensures idempotency (no dupes).
        """
        try:
            for exercise_id, sets in log.items():
                for i, entry in enumerate(sets, start=1):
                    self.save_strength_log_entry(
                        exercise_id=int(exercise_id),
                        log_date=date.fromisoformat(entry["date"]),
                        set_number=i,
                        reps=entry.get("reps"),
                        weight_kg=entry.get("weight"),
                        rir=entry.get("rir"),
                    )
        except Exception as e:
            log_utils.log_message(f"Error saving full lift log: {e}", "ERROR")

    def save_strength_log_entry(
        self,
        exercise_id: int,
        log_date: date,
        set_number: int,
        reps: int,
        weight_kg: float,
        rir: Optional[float] = None,
    ) -> None:
        """Insert a single set into ``strength_log`` with set ordering."""
        try:
            with get_conn() as conn:
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

    def update_strength_volume(self, log_date: date) -> None:
        """Aggregate total kg lifted (weight_kg * reps) for a day into daily_summary.strength_volume_kg."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT COALESCE(SUM(weight_kg * reps), 0) AS total FROM strength_log WHERE summary_date = %s;",
                        (log_date,),
                    )
                    total_volume = cur.fetchone()["total"]
                    cur.execute(
                        "UPDATE daily_summary SET strength_volume_kg = %s WHERE summary_date = %s;",
                        (total_volume, log_date),
                    )
            log_utils.log_message(
                f"[PostgresDal] Updated strength_volume_kg={total_volume} for {log_date.isoformat()}",
                "INFO",
            )
        except Exception as e:
            log_utils.log_message(
                f"Error updating strength volume for {log_date}: {e}", "ERROR"
            )

    # -------------------------------------------------------------------------
    # Daily summary
    # -------------------------------------------------------------------------
    def save_daily_summary(self, summary: Dict[str, Any], day: date) -> None:
        """Upserts a row into ``daily_summary``."""
        log_utils.log_message(f"[PostgresDal] Saving daily summary for {day.isoformat()}", "INFO")
        withings = summary.get("withings", {})
        apple = summary.get("apple", {})
        sleep = apple.get("sleep", {})

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO daily_summary (
                            summary_date, weight_kg, body_fat_pct, muscle_mass_kg, water_pct,
                            steps, exercise_minutes, calories_active, calories_resting, stand_minutes,
                            distance_m, hr_resting, hr_avg, hr_max, hr_min,
                            sleep_total_minutes, sleep_asleep_minutes, sleep_rem_minutes,
                            sleep_deep_minutes, sleep_core_minutes, sleep_awake_minutes
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            log_utils.log_message(f"Error saving daily summary to Postgres for {day}: {e}", "ERROR")

    def load_history(self) -> Dict[str, Any]:
        """Return all rows from ``daily_summary`` keyed by ISO date."""
        out: Dict[str, Any] = {}
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM daily_summary ORDER BY summary_date ASC;"
                    )
                    for row in cur.fetchall():
                        day = row["summary_date"].isoformat()
                        out[day] = self._row_to_summary(row)
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
        """Internal helper to convert a daily_summary row to the API shape."""
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
            "body_age_summary": {
                "years": float(row["body_age_years"]) if row.get("body_age_years") is not None else None,
                "delta_years": float(row["body_age_delta_years"]) if row.get("body_age_delta_years") is not None else None,
            },
            "strength": {
                "volume_kg": float(row["strength_volume_kg"]) if row.get("strength_volume_kg") is not None else None,
            },
        }

    # -------------------------------------------------------------------------
    # Body age
    # -------------------------------------------------------------------------
    def save_body_age(self, result: Dict[str, Any]) -> None:
        """Upsert a flattened body age record into body_age_log."""
        try:
            with get_conn() as conn:
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
            with get_conn() as conn:
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

    def calculate_and_save_body_age(self, start_date: date, end_date: date, profile: Dict[str, Any]) -> None:
        """Recalculate body age and persist into body_age_log + daily_summary headline fields."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT *
                        FROM daily_summary
                        WHERE summary_date BETWEEN %s AND %s
                        ORDER BY summary_date ASC;
                        """,
                        (start_date, end_date),
                    )
                    rows = cur.fetchall()

            if not rows:
                log_utils.log_message(
                    f"[BodyAge] No daily_summary data for window {start_date}..{end_date}", "WARN"
                )
                return

            withings_history: List[Dict[str, Any]] = []
            apple_history: List[Dict[str, Any]] = []
            for r in rows:
                withings_history.append({
                    "weight": r["weight_kg"],
                    "fat_percent": r["body_fat_pct"],
                    "muscle_mass": r["muscle_mass_kg"],
                    "water_percent": r["water_pct"],
                })
                apple_history.append({
                    "steps": r["steps"],
                    "exercise_minutes": r["exercise_minutes"],
                    "calories_active": r["calories_active"],
                    "calories_resting": r["calories_resting"],
                    "stand_minutes": r["stand_minutes"],
                    "distance_m": r["distance_m"],
                    "hr_resting": r["hr_resting"],
                    "hr_avg": r["hr_avg"],
                    "hr_max": r["hr_max"],
                    "hr_min": r["hr_min"],
                    "sleep_total_minutes": r["sleep_total_minutes"],
                    "sleep_asleep_minutes": r["sleep_asleep_minutes"],
                    "sleep_rem_minutes": r["sleep_rem_minutes"],
                    "sleep_deep_minutes": r["sleep_deep_minutes"],
                    "sleep_core_minutes": r["sleep_core_minutes"],
                    "sleep_awake_minutes": r["sleep_awake_minutes"],
                })

            result = body_age.calculate_body_age(
                withings_history=withings_history,
                apple_history=apple_history,
                profile=profile,
            )
            if not result:
                log_utils.log_message(
                    f"[BodyAge] No result produced for {end_date.isoformat()}", "WARN"
                )
                return

            result["date"] = end_date.isoformat()
            self.save_body_age(result)

            try:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE daily_summary
                            SET body_age_years = %s,
                                body_age_delta_years = %s
                            WHERE summary_date = %s;
                            """,
                            (
                                result.get("body_age_years"),
                                result.get("age_delta_years"),
                                end_date,
                            ),
                        )
                log_utils.log_message(
                    f"[BodyAge] Calculated and saved for {end_date.isoformat()}", "INFO"
                )
            except Exception as e:
                log_utils.log_message(
                    f"[BodyAge] Error updating headline fields for {end_date}: {e}", "ERROR"
                )
        except Exception as e:
            log_utils.log_message(
                f"Error calculating body age for {end_date}: {e}", "ERROR"
            )

    # -------------------------------------------------------------------------
    # Historical accessors
    # -------------------------------------------------------------------------
    def get_historical_metrics(self, days: int) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        try:
            with get_conn() as conn:
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
            with get_conn() as conn:
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
            with get_conn() as conn:
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

    # -------------------------------------------------------------------------
    # Training plans
    # -------------------------------------------------------------------------
    def save_training_plan(self, plan: dict, start_date: date) -> None:
        """Upsert a training plan into the training_plans table."""
        log_utils.log_message(
            f"[PostgresDal] Saving training plan for {start_date.isoformat()}", "INFO"
        )
        try:
            with get_conn() as conn:
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

    # -------------------------------------------------------------------------
    # Misc
    # -------------------------------------------------------------------------
    def save_validation_log(self, tag: str, adjustments: List[str]) -> None:
        """Persist validation logs via log utils."""
        log_utils.log_message(f"{tag}: {adjustments}", "INFO")
