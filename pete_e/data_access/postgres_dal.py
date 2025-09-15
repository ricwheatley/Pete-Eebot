"""
PostgreSQL implementation of the Data Access Layer.

Implements Pete-Eebot's relational schema:
- Source tables: withings_daily, apple_daily, wger_logs, body_age_daily
- Reference tables: Wger exercise catalog (refreshed separately)
- Training plans: training_plans → training_plan_weeks → training_plan_workouts
- Views: daily_summary, plan_muscle_volume, actual_muscle_volume
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional
import json

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from pete_e.config import settings
from pete_e.domain.user_helpers import calculate_age
from pete_e.infra import log_utils
from .dal import DataAccessLayer

# -------------------------------------------------------------------------
# Connection pool
# -------------------------------------------------------------------------
if not settings.DATABASE_URL:
    raise ValueError("DATABASE_URL is not set in the configuration. Cannot initialize connection pool.")

_pool = ConnectionPool(
    conninfo=settings.DATABASE_URL,
    min_size=1,
    max_size=3,
    max_lifetime=60,
    timeout=10,
)

def get_conn():
    return _pool.connection()

def close_pool():
    """Explicitly close the connection pool."""
    if not _pool.closed:
        _pool.close()
        log_utils.log_message("Database connection pool closed.", "INFO")


# -------------------------------------------------------------------------
# Postgres DAL
# -------------------------------------------------------------------------
class PostgresDal(DataAccessLayer):
    """
    PostgreSQL implementation of the Pete-Eebot Data Access Layer.
    """

    # ---------------------------------------------------------------------
    # Withings
    # ---------------------------------------------------------------------
    def save_withings_daily(self, day: date, weight_kg: float, body_fat_pct: float) -> None:
        try:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO withings_daily (date, weight_kg, body_fat_pct)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (date) DO UPDATE SET
                        weight_kg = EXCLUDED.weight_kg,
                        body_fat_pct = EXCLUDED.body_fat_pct;
                    """,
                    (day, weight_kg, body_fat_pct),
                )
        except Exception as e:
            log_utils.log_message(f"Error saving Withings data for {day}: {e}", "ERROR")

    # ---------------------------------------------------------------------
    # Apple
    # ---------------------------------------------------------------------
    def save_apple_daily(self, day: date, metrics: Dict[str, Any]) -> None:
        try:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO apple_daily (
                        date, steps, exercise_minutes, calories_active, calories_resting,
                        stand_minutes, distance_m, hr_resting, hr_avg, hr_max, hr_min,
                        sleep_total_minutes, sleep_asleep_minutes, sleep_rem_minutes,
                        sleep_deep_minutes, sleep_core_minutes, sleep_awake_minutes
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (date) DO UPDATE SET
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
                        day, metrics.get("steps"), metrics.get("exercise_minutes"),
                        metrics.get("calories_active"), metrics.get("calories_resting"),
                        metrics.get("stand_minutes"), metrics.get("distance_m"),
                        metrics.get("hr_resting"), metrics.get("hr_avg"),
                        metrics.get("hr_max"), metrics.get("hr_min"),
                        metrics.get("sleep_total_minutes"), metrics.get("sleep_asleep_minutes"),
                        metrics.get("sleep_rem_minutes"), metrics.get("sleep_deep_minutes"),
                        metrics.get("sleep_core_minutes"), metrics.get("sleep_awake_minutes"),
                    ),
                )
        except Exception as e:
            log_utils.log_message(f"Error saving Apple data for {day}: {e}", "ERROR")

    # ---------------------------------------------------------------------
    # Wger Logs
    # ---------------------------------------------------------------------
    def save_wger_log(
        self, day: date, exercise_id: int, set_number: int,
        reps: int, weight_kg: Optional[float], rir: Optional[float]
    ) -> None:
        try:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO wger_logs (date, exercise_id, set_number, reps, weight_kg, rir)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (date, exercise_id, set_number) DO UPDATE SET
                        reps = EXCLUDED.reps,
                        weight_kg = EXCLUDED.weight_kg,
                        rir = EXCLUDED.rir;
                    """,
                    (day, exercise_id, set_number, reps, weight_kg, rir),
                )
        except Exception as e:
            log_utils.log_message(f"Error saving Wger log for {day}, exercise {exercise_id}: {e}", "ERROR")

    def load_lift_log(self) -> Dict[str, Any]:
        """Compatibility: return all Wger logs grouped by exercise_id."""
        out: Dict[str, List[Dict[str, Any]]] = {}
        try:
            with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT * FROM wger_logs ORDER BY date ASC, exercise_id ASC, set_number ASC;")
                for row in cur.fetchall():
                    key = str(row["exercise_id"])
                    out.setdefault(key, []).append(row)
        except Exception as e:
            log_utils.log_message(f"Error loading lift log: {e}", "ERROR")
        return out

    # ---------------------------------------------------------------------
    # Body Age
    # ---------------------------------------------------------------------
    def save_body_age_daily(self, day: date, metrics: Dict[str, Any]) -> None:
        try:
            # ✨ Calculate actual age and delta here ✨
            body_age_years = metrics.get("body_age_years")
            body_age_delta_years = None

            if body_age_years is not None:
                actual_age = calculate_age(settings.USER_DATE_OF_BIRTH, on_date=day)
                body_age_delta_years = body_age_years - actual_age

            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO body_age_daily (
                        date, input_window_days, crf, body_comp, activity, recovery,
                        composite, body_age_years, body_age_delta_years,
                        used_vo2max_direct, cap_minus_10_applied
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (date) DO UPDATE SET
                        input_window_days = EXCLUDED.input_window_days, crf = EXCLUDED.crf,
                        body_comp = EXCLUDED.body_comp, activity = EXCLUDED.activity,
                        recovery = EXCLUDED.recovery, composite = EXCLUDED.composite,
                        body_age_years = EXCLUDED.body_age_years,
                        body_age_delta_years = EXCLUDED.body_age_delta_years,
                        used_vo2max_direct = EXCLUDED.used_vo2max_direct,
                        cap_minus_10_applied = EXCLUDED.cap_minus_10_applied;
                    """,
                    (
                        day,
                        metrics.get("input_window_days"),
                        metrics.get("crf"),
                        metrics.get("body_comp"),
                        metrics.get("activity"),
                        metrics.get("recovery"),
                        metrics.get("composite"),
                        body_age_years,
                        body_age_delta_years,
                        metrics.get("used_vo2max_direct"),
                        metrics.get("cap_minus_10_applied"),
                    ),
                )
        except Exception as e:
            log_utils.log_message(f"Error saving body age data for {day}: {e}", "ERROR")


    def get_daily_summary(self, target_date: date) -> Optional[Dict[str, Any]]:
        try:
            with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT * FROM daily_summary WHERE date = %s;", (target_date,))
                return cur.fetchone()
        except Exception as e:
            log_utils.log_message(f"Error fetching daily summary for {target_date}: {e}", "ERROR")
            return None

    def get_historical_metrics(self, days: int) -> List[Dict[str, Any]]:
        try:
            with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM daily_summary ORDER BY date DESC LIMIT %s;", (days,)
                )
                return list(reversed(cur.fetchall()))
        except Exception as e:
            log_utils.log_message(f"Error fetching historical metrics: {e}", "ERROR")
            return []

    def get_historical_data(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        try:
            with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT * FROM daily_summary
                    WHERE date BETWEEN %s AND %s
                    ORDER BY date ASC;
                    """,
                    (start_date, end_date),
                )
                return cur.fetchall()
        except Exception as e:
            log_utils.log_message(f"Error fetching historical data: {e}", "ERROR")
            return []
    
    # ---------------------------------------------------------------------
    # Training plans
    # ---------------------------------------------------------------------
    def save_training_plan(self, plan: dict, start_date: date) -> int:
        """Insert plan, weeks, and workouts in a single transaction."""
        try:
            with get_conn() as conn, conn.transaction(), conn.cursor() as cur:
                # 1. Deactivate any existing active plans
                cur.execute("UPDATE training_plans SET is_active = false WHERE is_active = true;")

                # 2. Insert the new plan and get its ID
                cur.execute(
                    "INSERT INTO training_plans (start_date, weeks, is_active) VALUES (%s, %s, true) RETURNING id;",
                    (start_date, len(plan.get("weeks", []))),
                )
                plan_id = cur.fetchone()[0]

                # 3. Insert weeks and workouts
                for week_num, week_data in enumerate(plan.get("weeks", []), 1):
                    cur.execute(
                        "INSERT INTO training_plan_weeks (plan_id, week_number) VALUES (%s, %s) RETURNING id;",
                        (plan_id, week_num),
                    )
                    week_id = cur.fetchone()[0]

                    for workout_data in week_data.get("workouts", []):
                        cur.execute(
                            """
                            INSERT INTO training_plan_workouts
                                (week_id, day_of_week, exercise_id, sets, reps, rir)
                            VALUES (%s, %s, %s, %s, %s, %s);
                            """,
                            (
                                week_id,
                                workout_data.get("day_of_week"),
                                workout_data.get("exercise_id"),
                                workout_data.get("sets"),
                                workout_data.get("reps"),
                                workout_data.get("rir"),
                            ),
                        )
                return plan_id
        except Exception as e:
            log_utils.log_message(f"Error saving training plan: {e}", "ERROR")
            return -1

    def get_plan(self, plan_id: int) -> Dict[str, Any]:
        """Fetches a full training plan with weeks and workouts."""
        # This is a complex query, you might build this out later if needed.
        # For now, a placeholder is fine.
        log_utils.log_message(f"Placeholder: Fetching plan {plan_id}", "INFO")
        return {}

    # ---------------------------------------------------------------------
    # Muscle volume comparison
    # ---------------------------------------------------------------------
    def get_plan_muscle_volume(self, plan_id: int, week_number: int) -> List[Dict[str, Any]]:
        """Fetch pre-calculated muscle volume for a given plan and week."""
        try:
            with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM plan_muscle_volume WHERE plan_id = %s AND week_number = %s;",
                    (plan_id, week_number),
                )
                return cur.fetchall()
        except Exception as e:
            log_utils.log_message(f"Error fetching plan muscle volume: {e}", "ERROR")
            return []

    def get_actual_muscle_volume(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        """Fetch actual muscle volume over a date range."""
        try:
            with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM actual_muscle_volume WHERE date BETWEEN %s AND %s;",
                    (start_date, end_date),
                )
                return cur.fetchall()
        except Exception as e:
            log_utils.log_message(f"Error fetching actual muscle volume: {e}", "ERROR")
            return []

    # ---------------------------------------------------------------------
    # Training Plan Helpers and Views
    # ---------------------------------------------------------------------

    def get_active_plan(self) -> Optional[Dict[str, Any]]:
        """Finds the current training plan marked as active."""
        try:
            with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT * FROM training_plans WHERE is_active = true LIMIT 1;")
                return cur.fetchone()
        except Exception as e:
            log_utils.log_message(f"Error fetching active plan: {e}", "ERROR")
            return None

    def get_plan_week(self, plan_id: int, week_number: int) -> List[Dict[str, Any]]:
        """Fetches all workouts for a specific week of a plan."""
        try:
            with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT tpw.*, e.name as exercise_name
                    FROM training_plan_workouts tpw
                    JOIN training_plan_weeks tw ON tpw.week_id = tw.id
                    JOIN wger_exercise e ON tpw.exercise_id = e.id
                    WHERE tw.plan_id = %s AND tw.week_number = %s
                    ORDER BY tpw.day_of_week;
                    """,
                    (plan_id, week_number),
                )
                return cur.fetchall()
        except Exception as e:
            log_utils.log_message(f"Error fetching plan week data: {e}", "ERROR")
            return []
    
    def refresh_plan_view(self) -> None:
        """Refreshes the materialized view for plan muscle volume."""
        try:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute("REFRESH MATERIALIZED VIEW plan_muscle_volume;")
                log_utils.log_message("Refreshed plan_muscle_volume view.", "INFO")
        except Exception as e:
            log_utils.log_message(f"Error refreshing plan_muscle_volume view: {e}", "ERROR")

    def refresh_actual_view(self) -> None:
        """Refreshes the materialized view for actual muscle volume."""
        try:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute("REFRESH MATERIALIZED VIEW actual_muscle_volume;")
                log_utils.log_message("Refreshed actual_muscle_volume view.", "INFO")
        except Exception as e:
            log_utils.log_message(f"Error refreshing actual_muscle_volume view: {e}", "ERROR")

    # ---------------------------------------------------------------------
    # Wger Catalog Upserts
    # ---------------------------------------------------------------------
    def upsert_wger_categories(self, categories: List[Dict[str, Any]]) -> None:
        success_count = 0
        for item in categories:
            try:
                # Get a fresh connection for each item
                with get_conn() as conn, conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO wger_category (id, name) VALUES (%(id)s, %(name)s)
                        ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name;
                        """,
                        item
                    )
                    success_count += 1
            except psycopg.Error as e:
                details = e.diag.message_primary if hasattr(e, 'diag') else 'No details'
                log_utils.log_message(f"Skipping category due to DB error. Details: {details} | Data: {item}", "WARN")
                continue
        log_utils.log_message(f"Successfully upserted {success_count}/{len(categories)} Wger categories.", "INFO")

    def upsert_wger_equipment(self, equipment: List[Dict[str, Any]]) -> None:
        success_count = 0
        for item in equipment:
            try:
                with get_conn() as conn, conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO wger_equipment (id, name) VALUES (%(id)s, %(name)s)
                        ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name;
                        """,
                        item
                    )
                    success_count += 1
            except psycopg.Error as e:
                details = e.diag.message_primary if hasattr(e, 'diag') else 'No details'
                log_utils.log_message(f"Skipping equipment due to DB error. Details: {details} | Data: {item}", "WARN")
                continue
        log_utils.log_message(f"Successfully upserted {success_count}/{len(equipment)} Wger equipment items.", "INFO")

    def upsert_wger_muscles(self, muscles: List[Dict[str, Any]]) -> None:
        success_count = 0
        for item in muscles:
            try:
                with get_conn() as conn, conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO wger_muscle (id, name, name_en, is_front)
                        VALUES (%(id)s, %(name)s, %(name_en)s, %(is_front)s)
                        ON CONFLICT (id) DO UPDATE SET
                            name = EXCLUDED.name, name_en = EXCLUDED.name_en, is_front = EXCLUDED.is_front;
                        """,
                        item
                    )
                    success_count += 1
            except psycopg.Error as e:
                details = e.diag.message_primary if hasattr(e, 'diag') else 'No details'
                log_utils.log_message(f"Skipping muscle due to DB error. Details: {details} | Data: {item}", "WARN")
                continue
        log_utils.log_message(f"Successfully upserted {success_count}/{len(muscles)} Wger muscles.", "INFO")

    def upsert_wger_exercises(self, exercises: List[Dict[str, Any]]) -> None:
        success_count = 0
        for ex in exercises:
            try:
                # Use a single connection and transaction for the entire exercise and its relations
                with get_conn() as conn, conn.cursor() as cur:
                    # Main exercise upsert
                    cur.execute(
                        """
                        INSERT INTO wger_exercise (id, uuid, name, description, category_id)
                        VALUES (%(id)s, %(uuid)s, %(name)s, %(description)s, %(category_id)s)
                        ON CONFLICT (id) DO UPDATE SET
                            uuid = EXCLUDED.uuid, name = EXCLUDED.name,
                            description = EXCLUDED.description, category_id = EXCLUDED.category_id;
                        """,
                        ex
                    )

                    # Junction tables
                    ex_id = ex['id']
                    if ex.get('equipment_ids'):
                        cur.execute("DELETE FROM wger_exercise_equipment WHERE exercise_id = %s;", (ex_id,))
                        equip_data = [(ex_id, eq_id) for eq_id in ex['equipment_ids']]
                        cur.executemany("INSERT INTO wger_exercise_equipment (exercise_id, equipment_id) VALUES (%s, %s);", equip_data)
                    
                    if ex.get('primary_muscle_ids'):
                        cur.execute("DELETE FROM wger_exercise_muscle_primary WHERE exercise_id = %s;", (ex_id,))
                        primary_data = [(ex_id, m_id) for m_id in ex['primary_muscle_ids']]
                        cur.executemany("INSERT INTO wger_exercise_muscle_primary (exercise_id, muscle_id) VALUES (%s, %s);", primary_data)

                    if ex.get('secondary_muscle_ids'):
                        cur.execute("DELETE FROM wger_exercise_muscle_secondary WHERE exercise_id = %s;", (ex_id,))
                        secondary_data = [(ex_id, m_id) for m_id in ex['secondary_muscle_ids']]
                        cur.executemany("INSERT INTO wger_exercise_muscle_secondary (exercise_id, muscle_id) VALUES (%s, %s);", secondary_data)
                    
                    success_count += 1
            except psycopg.Error as e:
                details = e.diag.message_primary if hasattr(e, 'diag') else 'No details'
                log_utils.log_message(f"Skipping exercise due to DB error. Details: {details} | Data: {ex}", "WARN")
                continue
        
        log_utils.log_message(f"Successfully upserted {success_count}/{len(exercises)} Wger exercises.", "INFO")

    def save_validation_log(self, tag: str, adjustments: List[str]) -> None:
        log_utils.log_message(f"[VALIDATION] {tag}: {adjustments}", "INFO")