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
                        day,
                        metrics.get("steps"),
                        metrics.get("exercise_minutes"),
                        metrics.get("calories_active"),
                        metrics.get("calories_resting"),
                        metrics.get("stand_minutes"),
                        metrics.get("distance_m"),
                        metrics.get("hr_resting"),
                        metrics.get("hr_avg"),
                        metrics.get("hr_max"),
                        metrics.get("hr_min"),
                        metrics.get("sleep_total_minutes"),
                        metrics.get("sleep_asleep_minutes"),
                        metrics.get("sleep_rem_minutes"),
                        metrics.get("sleep_deep_minutes"),
                        metrics.get("sleep_core_minutes"),
                        metrics.get("sleep_awake_minutes"),
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
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO body_age_daily (
                        date, input_window_days,
                        crf, body_comp, activity, recovery,
                        composite, body_age_years, body_age_delta_years,
                        used_vo2max_direct, cap_minus_10_applied
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (date) DO UPDATE SET
                        input_window_days = EXCLUDED.input_window_days,
                        crf = EXCLUDED.crf,
                        body_comp = EXCLUDED.body_comp,
                        activity = EXCLUDED.activity,
                        recovery = EXCLUDED.recovery,
                        composite = EXCLUDED.composite,
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
                        metrics.get("body_age_years"),
                        metrics.get("body_age_delta_years"),
                        metrics.get("used_vo2max_direct"),
                        metrics.get("cap_minus_10_applied"),
                    ),
                )
        except Exception as e:
            log_utils.log_message(f"Error saving body age data for {day}: {e}", "ERROR")

    # ---------------------------------------------------------------------
    # Summaries (views)
    # ---------------------------------------------------------------------
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
    # Training Plans
    # ---------------------------------------------------------------------
    def save_training_plan(self, plan: dict, start_date: date) -> int:
        """
        Save a normalized training plan (plan → weeks → workouts).
        Returns the plan_id.
        """
        plan_id = None
        try:
            with get_conn() as conn, conn.cursor() as cur:
                # Insert plan
                cur.execute(
                    """
                    INSERT INTO training_plans (start_date, weeks, is_active)
                    VALUES (%s, %s, true)
                    ON CONFLICT (start_date) DO UPDATE SET weeks = EXCLUDED.weeks
                    RETURNING id;
                    """,
                    (start_date, len(plan.get("weeks", []))),
                )
                plan_id = cur.fetchone()[0]

                # Insert weeks + workouts
                for week in plan.get("weeks", []):
                    week_number = week["week_number"]
                    cur.execute(
                        """
                        INSERT INTO training_plan_weeks (plan_id, week_number)
                        VALUES (%s, %s)
                        ON CONFLICT DO NOTHING
                        RETURNING id;
                        """,
                        (plan_id, week_number),
                    )
                    week_id = cur.fetchone()[0]
                    for workout in week.get("workouts", []):
                        cur.execute(
                            """
                            INSERT INTO training_plan_workouts
                                (week_id, day_of_week, exercise_id, sets, reps, rir)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT DO NOTHING;
                            """,
                            (
                                week_id,
                                workout["day_of_week"],
                                workout["exercise_id"],
                                workout["sets"],
                                workout["reps"],
                                workout.get("rir"),
                            ),
                        )
            return plan_id
        except Exception as e:
            log_utils.log_message(f"Error saving training plan for {start_date}: {e}", "ERROR")
            return plan_id

    def get_plan(self, plan_id: int) -> Dict[str, Any]:
        out: Dict[str, Any] = {"id": plan_id, "weeks": []}
        try:
            with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT * FROM training_plans WHERE id = %s;", (plan_id,))
                out.update(cur.fetchone() or {})

                cur.execute("SELECT * FROM training_plan_weeks WHERE plan_id = %s;", (plan_id,))
                weeks = cur.fetchall()
                for week in weeks:
                    cur.execute(
                        "SELECT * FROM training_plan_workouts WHERE week_id = %s;",
                        (week["id"],),
                    )
                    week["workouts"] = cur.fetchall()
                out["weeks"] = weeks
        except Exception as e:
            log_utils.log_message(f"Error fetching training plan {plan_id}: {e}", "ERROR")
        return out

    # ---------------------------------------------------------------------
    # Muscle Volume Views
    # ---------------------------------------------------------------------
    def get_plan_muscle_volume(self, plan_id: int, week_number: int) -> List[Dict[str, Any]]:
        try:
            with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT * FROM plan_muscle_volume
                    WHERE plan_id = %s AND week_number = %s;
                    """,
                    (plan_id, week_number),
                )
                return cur.fetchall()
        except Exception as e:
            log_utils.log_message(f"Error fetching plan muscle volume: {e}", "ERROR")
            return []

    def get_actual_muscle_volume(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        try:
            with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT * FROM actual_muscle_volume
                    WHERE date BETWEEN %s AND %s;
                    """,
                    (start_date, end_date),
                )
                return cur.fetchall()
        except Exception as e:
            log_utils.log_message(f"Error fetching actual muscle volume: {e}", "ERROR")
            return []

    # ---------------------------------------------------------------------
    # Validation logs
    # ---------------------------------------------------------------------
    def save_validation_log(self, tag: str, adjustments: List[str]) -> None:
        log_utils.log_message(f"[VALIDATION] {tag}: {adjustments}", "INFO")
