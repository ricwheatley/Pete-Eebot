# pete_e/infrastructure/postgres_dal.py
"""
The single, consolidated Data Access Layer for all PostgreSQL interactions.
This class implements the DataAccessLayer interface and handles all database
reads, writes, and catalog management.
"""
from __future__ import annotations
import json
import hashlib
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Json
from psycopg_pool import ConnectionPool

from pete_e.config import settings
from pete_e.infrastructure.db_conn import get_database_url
from pete_e.infrastructure import log_utils
from pete_e.domain.repositories import PlanRepository

# --- Connection Pool Management ---
_pool: ConnectionPool | None = None

def _create_pool() -> ConnectionPool:
    db_url = get_database_url()
    return ConnectionPool(conninfo=db_url, min_size=1, max_size=5)

def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = _create_pool()
    return _pool

# --- Data Access Layer ---
class PostgresDal(PlanRepository):
    """PostgreSQL implementation of the Data Access Layer."""

    def __init__(self, pool: Optional[ConnectionPool] = None):
        self.pool = pool or get_pool()

    @contextmanager
    def _get_cursor(self, use_dict_row: bool = True):
        row_factory = dict_row if use_dict_row else None
        with self.pool.connection() as conn:
            cursor_factory = conn.cursor(row_factory=row_factory) if use_dict_row else conn.cursor()
            with cursor_factory as cur:
                if use_dict_row:
                    cur.row_factory = dict_row
                yield cur

    def connection(self):
        """Provide a context manager for a pooled database connection."""
        return self.pool.connection()
    
    def close(self) -> None:
        if self.pool and not self.pool.closed:
            self.pool.close()
            log_utils.info("Database connection pool closed.")

    # ----------------------------------------------
    # --- Plan & Block Management ---
    # ----------------------------------------------
    def save_full_plan(self, plan_dict: Dict[str, Any]) -> int:
        raise NotImplementedError

    def get_assistance_pool_for(self, main_lift_id: int) -> List[int]:
        return []

    def get_core_pool_ids(self) -> List[int]:
        return []

    def create_block_and_plan(self, start_date: date, weeks: int = 4) -> Tuple[int, List[int]]:
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=None) as cur:
                try:
                    conn.autocommit = False
                    cur.execute("UPDATE training_plans SET is_active = false WHERE is_active = true;")
                    cur.execute("INSERT INTO training_plans(start_date, weeks, is_active) VALUES (%s, %s, true) RETURNING id;", (start_date, weeks))
                    plan_id = cur.fetchone()[0]
                    week_ids: List[int] = []
                    for w in range(1, weeks + 1):
                        cur.execute("INSERT INTO training_plan_weeks(plan_id, week_number) VALUES (%s, %s) RETURNING id;", (plan_id, w))
                        week_ids.append(cur.fetchone()[0])
                    conn.commit()
                    return plan_id, week_ids
                except Exception:
                    conn.rollback()
                    raise

    def insert_workout(self, **kwargs) -> None:
        sql = "INSERT INTO training_plan_workouts (week_id, day_of_week, exercise_id, sets, reps, rir, percent_1rm, target_weight_kg, scheduled_time, is_cardio) VALUES (%(week_id)s, %(day_of_week)s, %(exercise_id)s, %(sets)s, %(reps)s, %(rir_cue)s, %(percent_1rm)s, %(target_weight_kg)s, %(scheduled_time)s, %(is_cardio)s);"
        with self._get_cursor() as cur:
            cur.execute(sql, kwargs)

    def get_active_plan(self) -> Optional[Dict[str, Any]]:
        sql = "SELECT * FROM training_plans WHERE is_active = true ORDER BY id DESC LIMIT 1;"
        with self._get_cursor() as cur:
            cur.execute(sql)
            return cur.fetchone()

    def get_plan_week_rows(self, plan_id: int, week_number: int) -> List[Dict[str, Any]]:
        sql = "SELECT tpw.*, tw.week_number FROM training_plan_workouts tpw JOIN training_plan_weeks tw ON tw.id = tpw.week_id WHERE tw.plan_id = %s AND tw.week_number = %s ORDER BY tpw.day_of_week, tpw.id;"
        with self._get_cursor() as cur:
            cur.execute(sql, (plan_id, week_number))
            return cur.fetchall()

    def get_plan_for_day(self, target_date: date) -> Tuple[List[str], List[Tuple[Any, ...]]]:
        return self._call_function("sp_plan_for_day", target_date)

    def get_plan_for_week(self, start_date: date) -> Tuple[List[str], List[Tuple[Any, ...]]]:
        return self._call_function("sp_plan_for_week", start_date)

    def get_week_ids_for_plan(self, plan_id: int) -> Dict[int, int]:
        sql = "SELECT id, week_number FROM training_plan_weeks WHERE plan_id = %s;"
        out: Dict[int, int] = {}
        with self._get_cursor() as cur:
            cur.execute(sql, (plan_id,))
            for r in cur.fetchall():
                out[r["week_number"]] = r["id"]
        return out

    def find_plan_by_start_date(self, start_date: date) -> Optional[Dict[str, Any]]:
        sql = "SELECT * FROM training_plans WHERE start_date = %s ORDER BY id DESC LIMIT 1;"
        with self._get_cursor() as cur:
            cur.execute(sql, (start_date,))
            return cur.fetchone()

    def has_any_plan(self) -> bool:
        with self._get_cursor(use_dict_row=False) as cur:
            cur.execute("SELECT EXISTS (SELECT 1 FROM training_plans);")
            row = cur.fetchone()
            return bool(row[0]) if row else False

    def update_workout_targets(self, updates: List[Dict[str, Any]]) -> None:
        if not updates: return
        payload = [(item.get("target_weight_kg"), item.get("workout_id")) for item in updates if item.get("workout_id") is not None]
        if not payload: return
        with self._get_cursor() as cur:
            cur.executemany("UPDATE training_plan_workouts SET target_weight_kg = %s WHERE id = %s", payload)

    def apply_plan_backoff(self, week_start_date: date, set_multiplier: float, rir_increment: int) -> None:
        with self._get_cursor() as cur:
            cur.execute("SELECT id, start_date, weeks FROM training_plans WHERE start_date <= %s ORDER BY start_date DESC LIMIT 1;", (week_start_date,))
            plan = cur.fetchone()
            if not plan: return
            
            week_number = ((week_start_date - plan['start_date']).days // 7) + 1
            if not (1 <= week_number <= plan['weeks']): return

            cur.execute("SELECT id FROM training_plan_weeks WHERE plan_id = %s AND week_number = %s;", (plan['id'], week_number))
            week = cur.fetchone()
            if not week: return
            
            cur.execute("UPDATE training_plan_workouts SET sets = GREATEST(1, ROUND(sets * %s)::int), rir = CASE WHEN rir IS NULL THEN %s ELSE rir + %s END WHERE week_id = %s AND is_cardio = false;", (set_multiplier, rir_increment, rir_increment, week['id']))
            log_utils.info(f"Applied plan back-off to week {week_number} (plan_id={plan['id']}).")

    # ----------------------------------------------
    # --- Strength Test & Training Max Management ---
    # ----------------------------------------------
    def create_test_week_plan(self, start_date: date) -> Tuple[int, int]:
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=None) as cur:
                try:
                    conn.autocommit = False
                    cur.execute("UPDATE training_plans SET is_active = false WHERE is_active = true;")
                    cur.execute("INSERT INTO training_plans(start_date, weeks, is_active) VALUES (%s, 1, true) RETURNING id;", (start_date,))
                    plan_id = cur.fetchone()[0]
                    cur.execute("INSERT INTO training_plan_weeks(plan_id, week_number, is_test) VALUES (%s, 1, true) RETURNING id;", (plan_id,))
                    week_id = cur.fetchone()[0]
                    conn.commit()
                    return plan_id, week_id
                except Exception:
                    conn.rollback()
                    raise

    def get_latest_test_week(self) -> Optional[Dict[str, Any]]:
        sql = "SELECT tw.id AS week_id, tw.week_number, tw.is_test, tp.id AS plan_id, tp.start_date, tp.weeks FROM training_plan_weeks tw JOIN training_plans tp ON tp.id = tw.plan_id WHERE tw.is_test = true ORDER BY tp.start_date DESC LIMIT 1;"
        with self._get_cursor() as cur:
            cur.execute(sql)
            return cur.fetchone()

    def insert_strength_test_result(self, **kwargs) -> None:
        sql = "INSERT INTO strength_test_result (plan_id, week_number, lift_code, test_date, test_reps, test_weight_kg, e1rm_kg, tm_kg) VALUES (%(plan_id)s, %(week_number)s, %(lift_code)s, %(test_date)s, %(test_reps)s, %(test_weight_kg)s, %(e1rm_kg)s, %(tm_kg)s) ON CONFLICT (plan_id, week_number, lift_code) DO NOTHING;"
        with self._get_cursor() as cur:
            cur.execute(sql, kwargs)

    def upsert_training_max(self, lift_code: str, tm_kg: float, measured_at: date, source: str) -> None:
        sql = "INSERT INTO training_max (lift_code, tm_kg, source, measured_at) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING;"
        with self._get_cursor() as cur:
            cur.execute(sql, (lift_code, tm_kg, source, measured_at))

    def get_latest_training_maxes(self) -> Dict[str, Optional[float]]:
        sql = "SELECT DISTINCT ON (lift_code) lift_code, tm_kg FROM training_max ORDER BY lift_code, measured_at DESC;"
        out: Dict[str, Optional[float]] = {}
        with self._get_cursor() as cur:
            cur.execute(sql)
            for row in cur.fetchall():
                out[row["lift_code"]] = row["tm_kg"]
        return out

    def get_latest_training_max_date(self) -> Optional[date]:
        sql = "SELECT MAX(measured_at) AS latest FROM training_max;"
        with self._get_cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
            if not row or not row.get("latest"): return None
            latest = row["latest"]
            return latest.date() if isinstance(latest, datetime) else latest
    
    # ----------------------------------------------
    # --- Wger & Withings Log Management ---
    # ----------------------------------------------
    def save_withings_daily(self, day: date, weight_kg: Optional[float], body_fat_pct: Optional[float], muscle_pct: Optional[float], water_pct: Optional[float]) -> None:
        sql = "INSERT INTO withings_daily (date, weight_kg, body_fat_pct, muscle_pct, water_pct) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (date) DO UPDATE SET weight_kg = EXCLUDED.weight_kg, body_fat_pct = EXCLUDED.body_fat_pct, muscle_pct = EXCLUDED.muscle_pct, water_pct = EXCLUDED.water_pct;"
        with self._get_cursor() as cur:
            cur.execute(sql, (day, weight_kg, body_fat_pct, muscle_pct, water_pct))

    def save_wger_log(self, day: date, exercise_id: int, set_number: int, reps: int, weight_kg: Optional[float], rir: Optional[float]) -> None:
        sql = "INSERT INTO wger_logs (date, exercise_id, set_number, reps, weight_kg, rir) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (date, exercise_id, set_number) DO UPDATE SET reps = EXCLUDED.reps, weight_kg = EXCLUDED.weight_kg, rir = EXCLUDED.rir;"
        with self._get_cursor() as cur:
            cur.execute(sql, (day, exercise_id, set_number, reps, weight_kg, rir))

    def load_lift_log(self, exercise_ids: List[int], start_date: Optional[date] = None, end_date: Optional[date] = None) -> Dict[str, Any]:
        out: Dict[str, List[Dict[str, Any]]] = {}
        sql_parts = ["SELECT * FROM wger_logs WHERE exercise_id = ANY(%s)"]
        params: List[Any] = [exercise_ids]
        if start_date: sql_parts.append("AND date >= %s"); params.append(start_date)
        if end_date: sql_parts.append("AND date <= %s"); params.append(end_date)
        sql_parts.append("ORDER BY date, set_number;")
        
        with self._get_cursor() as cur:
            cur.execute(" ".join(sql_parts), params)
            for row in cur.fetchall():
                out.setdefault(str(row["exercise_id"]), []).append(row)
        return out
        
    # ----------------------------------------------
    # --- Wger Catalog & Seeding ---
    # ----------------------------------------------
    def _bulk_upsert(self, table_name: str, data: List[Dict[str, Any]], conflict_keys: List[str], update_keys: List[str]):
        if not data: return
        cols = list(data[0].keys())
        placeholders = sql.SQL(",").join(sql.Placeholder() * len(cols))
        conflict_action = sql.SQL("DO UPDATE SET {updates}").format(updates=sql.SQL(",").join(sql.SQL("{} = EXCLUDED.{}").format(sql.Identifier(k), sql.Identifier(k)) for k in update_keys)) if update_keys else sql.SQL("DO NOTHING")
        stmt = sql.SQL("INSERT INTO {table} ({cols}) VALUES ({p}) ON CONFLICT ({c_keys}) {action}").format(table=sql.Identifier(table_name), cols=sql.SQL(",").join(map(sql.Identifier, cols)), p=placeholders, c_keys=sql.SQL(",").join(map(sql.Identifier, conflict_keys)), action=conflict_action)
        values = [[row.get(c) for c in cols] for row in data]
        with self._get_cursor() as cur:
            cur.executemany(stmt, values)
            log_utils.info(f"Upserted {len(data)} rows into \"{table_name}\".")

    def upsert_wger_exercises_and_relations(self, exercises: List[Dict[str, Any]]):
        if not exercises: return
        exercise_data = [{"id": ex["id"], "uuid": ex["uuid"], "name": ex["name"], "description": ex["description"], "category_id": ex["category_id"]} for ex in exercises]
        self._bulk_upsert("wger_exercise", exercise_data, ["id"], ["uuid", "name", "description", "category_id"])
        equipment, primary, secondary, exercise_ids = [], [], [], [ex["id"] for ex in exercises]
        for ex in exercises:
            for eq_id in ex["equipment_ids"]: equipment.append({"exercise_id": ex["id"], "equipment_id": eq_id})
            for m_id in ex["primary_muscle_ids"]: primary.append({"exercise_id": ex["id"], "muscle_id": m_id})
            for m_id in ex["secondary_muscle_ids"]: secondary.append({"exercise_id": ex["id"], "muscle_id": m_id})
        with self._get_cursor() as cur:
            cur.execute('DELETE FROM wger_exercise_equipment WHERE exercise_id = ANY(%s)', (exercise_ids,)); cur.execute('DELETE FROM wger_exercise_muscle_primary WHERE exercise_id = ANY(%s)', (exercise_ids,)); cur.execute('DELETE FROM wger_exercise_muscle_secondary WHERE exercise_id = ANY(%s)', (exercise_ids,))
        if equipment: self._bulk_upsert("wger_exercise_equipment", equipment, ["exercise_id", "equipment_id"], [])
        if primary: self._bulk_upsert("wger_exercise_muscle_primary", primary, ["exercise_id", "muscle_id"], [])
        if secondary: self._bulk_upsert("wger_exercise_muscle_secondary", secondary, ["exercise_id", "muscle_id"], [])

    def seed_main_lifts_and_assistance(self, main_lift_ids: List[int], assistance_pool_data: List[Tuple[int, List[int]]]):
        with self._get_cursor() as cur:
            cur.execute('UPDATE wger_exercise SET is_main_lift = true WHERE id = ANY(%s)', (main_lift_ids,))
            assistance_values = [(main, assist) for main, assists in assistance_pool_data for assist in assists]
            if assistance_values:
                stmt = sql.SQL("INSERT INTO assistance_pool (main_exercise_id, assistance_exercise_id) VALUES (%s, %s) ON CONFLICT DO NOTHING")
                cur.executemany(stmt, assistance_values)
        log_utils.info("Seeding of main lifts and assistance pools complete.")

    # ----------------------------------------------
    # --- Metrics, Summaries & Views ---
    # ----------------------------------------------
    def get_historical_data(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM daily_summary WHERE date BETWEEN %s AND %s ORDER BY date ASC;"
        with self._get_cursor() as cur:
            cur.execute(sql, (start_date, end_date))
            return cur.fetchall()

    def get_historical_metrics(self, days: int) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM daily_summary ORDER BY date DESC LIMIT %s;"
        with self._get_cursor() as cur:
            cur.execute(sql, (days,))
            return list(reversed(cur.fetchall()))

    def get_metrics_overview(self, target_date: date) -> Tuple[List[str], List[Tuple[Any, ...]]]:
        return self._call_function("sp_metrics_overview", target_date)
    
    def refresh_daily_summary(self, days: int = 7) -> None:
        start_date = date.today() - timedelta(days=days); end_date = date.today()
        with self._get_cursor() as cur:
            cur.execute("SELECT sp_upsert_body_age_range(%s, %s, %s);", (start_date, end_date, settings.USER_DATE_OF_BIRTH))
            cur.execute("SELECT sp_refresh_daily_summary(%s, %s);", (start_date, end_date))
        log_utils.info(f"Refreshed body_age_daily and daily_summary for last {days} days.")

    def get_plan_muscle_volume(self, plan_id: int, week_number: int) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM plan_muscle_volume WHERE plan_id = %s AND week_number = %s;"
        with self._get_cursor() as cur:
            cur.execute(sql, (plan_id, week_number))
            return cur.fetchall()

    def get_actual_muscle_volume(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM actual_muscle_volume WHERE date BETWEEN %s AND %s;"
        with self._get_cursor() as cur:
            cur.execute(sql, (start_date, end_date))
            return cur.fetchall()

    def refresh_plan_view(self) -> None:
        with self._get_cursor() as cur: cur.execute("REFRESH MATERIALIZED VIEW plan_muscle_volume;")
    
    def refresh_actual_view(self) -> None:
        with self._get_cursor() as cur: cur.execute("REFRESH MATERIALIZED VIEW actual_muscle_volume;")

    # ----------------------------------------------
    # --- Export & Validation Logging ---
    # ----------------------------------------------
    def was_week_exported(self, plan_id: int, week_number: int) -> bool:
        sql = "SELECT 1 FROM wger_export_log WHERE plan_id = %s AND week_number = %s LIMIT 1;"
        with self._get_cursor(use_dict_row=False) as cur:
            cur.execute(sql, (plan_id, week_number))
            return cur.fetchone() is not None

    def record_wger_export(self, plan_id: int, week_number: int, payload: Dict[str, Any], response: Optional[Dict[str, Any]] = None, routine_id: Optional[int] = None):
        body = json.dumps(payload, sort_keys=True)
        checksum = hashlib.sha1(f"{plan_id}:{week_number}:{body}".encode("utf-8")).hexdigest()
        sql = "INSERT INTO wger_export_log(plan_id, week_number, payload_json, response_json, checksum, routine_id) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (plan_id, week_number, checksum) DO NOTHING;"
        with self._get_cursor() as cur:
            cur.execute(sql, (plan_id, week_number, Json(payload), Json(response or {}), checksum, routine_id))
    
    def save_validation_log(self, tag: str, adjustments: List[str]) -> None:
        # This was just a log message, so we'll keep it that way.
        log_utils.info(f"[VALIDATION] {tag}: {adjustments}")
    def _call_function(self, function_name: str, *params: Any) -> Tuple[List[str], List[Tuple[Any, ...]]]:
        """Execute a SQL function and return column names and rows."""
        with self._get_cursor(use_dict_row=False) as cur:
            if params:
                placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in params)
                stmt = sql.SQL("SELECT * FROM {function_name}({params});").format(
                    function_name=sql.Identifier(function_name),
                    params=placeholders,
                )
            else:
                stmt = sql.SQL("SELECT * FROM {function_name}();").format(
                    function_name=sql.Identifier(function_name)
                )

            cur.execute(stmt, params)
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
        return columns, rows
