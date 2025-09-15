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


# -------------------------------------------------------------------------
# Postgres DAL
# -------------------------------------------------------------------------
class PostgresDal(DataAccessLayer):
    """
    PostgreSQL implementation of the Pete-Eebot Data Access Layer.
    """

    # ... (existing methods for Withings, Apple, Wger Logs, etc. remain unchanged) ...
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
                        body_age_delta_years, # <-- Use the calculated delta
                        metrics.get("used_vo2max_direct"),
                        metrics.get("cap_minus_10_applied"),
                    ),
                )
        except Exception as e:
            log_utils.log_message(f"Error saving body age data for {day}: {e}", "ERROR")

    # ... (summary and training plan methods are also unchanged) ...
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
    # Wger Catalog Upserts
    # ---------------------------------------------------------------------
    def upsert_wger_categories(self, categories: List[Dict[str, Any]]) -> None:
        """Upserts a list of categories into the wger_category table."""
        try:
            with get_conn() as conn, conn.cursor() as cur:
                stmt = """
                    INSERT INTO wger_category (id, name)
                    VALUES (%(id)s, %(name)s)
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name;
                """
                cur.executemany(stmt, categories)
                log_utils.log_message(f"Upserted {len(categories)} Wger categories.", "INFO")
        except Exception as e:
            log_utils.log_message(f"Error upserting Wger categories: {e}", "ERROR")

    def upsert_wger_equipment(self, equipment: List[Dict[str, Any]]) -> None:
        """Upserts a list of equipment into the wger_equipment table."""
        try:
            with get_conn() as conn, conn.cursor() as cur:
                stmt = """
                    INSERT INTO wger_equipment (id, name)
                    VALUES (%(id)s, %(name)s)
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name;
                """
                cur.executemany(stmt, equipment)
                log_utils.log_message(f"Upserted {len(equipment)} Wger equipment items.", "INFO")
        except Exception as e:
            log_utils.log_message(f"Error upserting Wger equipment: {e}", "ERROR")

    def upsert_wger_muscles(self, muscles: List[Dict[str, Any]]) -> None:
        """Upserts a list of muscles into the wger_muscle table."""
        try:
            with get_conn() as conn, conn.cursor() as cur:
                stmt = """
                    INSERT INTO wger_muscle (id, name, name_en, is_front)
                    VALUES (%(id)s, %(name)s, %(name_en)s, %(is_front)s)
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name,
                        name_en = EXCLUDED.name_en,
                        is_front = EXCLUDED.is_front;
                """
                cur.executemany(stmt, muscles)
                log_utils.log_message(f"Upserted {len(muscles)} Wger muscles.", "INFO")
        except Exception as e:
            log_utils.log_message(f"Error upserting Wger muscles: {e}", "ERROR")

    def upsert_wger_exercises(self, exercises: List[Dict[str, Any]]) -> None:
        """
        Upserts exercises and their many-to-many relationships in a single transaction.
        """
        try:
            with get_conn() as conn, conn.transaction(), conn.cursor() as cur:
                # 1. Upsert main exercise data
                stmt_exercise = """
                    INSERT INTO wger_exercise (id, uuid, name, description, category_id)
                    VALUES (%(id)s, %(uuid)s, %(name)s, %(description)s, %(category_id)s)
                    ON CONFLICT (id) DO UPDATE SET
                        uuid = EXCLUDED.uuid,
                        name = EXCLUDED.name,
                        description = EXCLUDED.description,
                        category_id = EXCLUDED.category_id;
                """
                cur.executemany(stmt_exercise, exercises)

                # 2. Upsert junction table data (delete and re-insert for simplicity)
                for ex in exercises:
                    ex_id = ex['id']

                    # Equipment
                    cur.execute("DELETE FROM wger_exercise_equipment WHERE exercise_id = %s;", (ex_id,))
                    if ex.get('equipment_ids'):
                        equip_data = [(ex_id, eq_id) for eq_id in ex['equipment_ids']]
                        cur.executemany("INSERT INTO wger_exercise_equipment (exercise_id, equipment_id) VALUES (%s, %s);", equip_data)

                    # Primary Muscles
                    cur.execute("DELETE FROM wger_exercise_muscle_primary WHERE exercise_id = %s;", (ex_id,))
                    if ex.get('primary_muscle_ids'):
                        primary_data = [(ex_id, m_id) for m_id in ex['primary_muscle_ids']]
                        cur.executemany("INSERT INTO wger_exercise_muscle_primary (exercise_id, muscle_id) VALUES (%s, %s);", primary_data)

                    # Secondary Muscles
                    cur.execute("DELETE FROM wger_exercise_muscle_secondary WHERE exercise_id = %s;", (ex_id,))
                    if ex.get('secondary_muscle_ids'):
                        secondary_data = [(ex_id, m_id) for m_id in ex['secondary_muscle_ids']]
                        cur.executemany("INSERT INTO wger_exercise_muscle_secondary (exercise_id, muscle_id) VALUES (%s, %s);", secondary_data)

                log_utils.log_message(f"Upserted {len(exercises)} Wger exercises and their relations.", "INFO")
        except Exception as e:
            log_utils.log_message(f"Error upserting Wger exercises: {e}", "ERROR")

    # ... (all other methods remain) ...
    def save_validation_log(self, tag: str, adjustments: List[str]) -> None:
        log_utils.log_message(f"[VALIDATION] {tag}: {adjustments}", "INFO")