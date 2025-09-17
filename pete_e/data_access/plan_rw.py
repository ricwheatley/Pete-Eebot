# pete_e/data_access/plan_rw.py
#
# Psycopg 3 data access helpers for planner, reviewer and exporter.
# One place for DB reads/writes used by planner_v2, weekly_reviewer_v2 and wger_exporter_v2.
#
# Requirements:
#   pip install "psycopg[binary]>=3.1,<4"
#
# Env:
#   DATABASE_URL = postgresql://user:pass@host:port/dbname
#

import os
import json
import hashlib
from contextlib import contextmanager
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Tuple

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json


DATABASE_URL = os.getenv("DATABASE_URL")


@contextmanager
def conn_cursor():
    """
    Yields a (conn, cur) pair with dict rows and an implicit transaction.
    Commits on success, rolls back on exception.
    """
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    try:
        with conn:
            with conn.cursor() as cur:
                yield conn, cur
    finally:
        conn.close()


# ---------------------------
# Reads
# ---------------------------

def latest_training_max() -> Dict[str, Optional[float]]:
    """
    Return latest TM per lift_code, e.g. {'squat': 180.0, 'bench': 120.0, ...}
    """
    sql = """
    SELECT DISTINCT ON (lift_code) lift_code, tm_kg
    FROM training_max
    ORDER BY lift_code, measured_at DESC;
    """
    out: Dict[str, Optional[float]] = {}
    with conn_cursor() as (_, cur):
        cur.execute(sql)
        for row in cur.fetchall():
            out[row["lift_code"]] = row["tm_kg"]
    return out


def assistance_pool_for(main_exercise_id: int) -> List[int]:
    sql = """
    SELECT assistance_exercise_id
    FROM assistance_pool
    WHERE main_exercise_id = %s
    ORDER BY assistance_exercise_id;
    """
    with conn_cursor() as (_, cur):
        cur.execute(sql, (main_exercise_id,))
        return [r["assistance_exercise_id"] for r in cur.fetchall()]


def core_pool_ids() -> List[int]:
    """
    Return a list of exercise ids that hit Abs or Obliques as primary or secondary.
    """
    sql = """
    WITH core_m AS (
      SELECT id FROM wger_muscle WHERE lower(name) IN ('abs','abdominals','obliques')
    )
    SELECT DISTINCT e.id
    FROM wger_exercise e
    LEFT JOIN wger_exercise_muscle_primary p ON p.exercise_id = e.id
    LEFT JOIN wger_exercise_muscle_secondary s ON s.exercise_id = e.id
    WHERE p.muscle_id IN (SELECT id FROM core_m)
       OR s.muscle_id IN (SELECT id FROM core_m)
    ORDER BY e.id;
    """
    with conn_cursor() as (_, cur):
        cur.execute(sql)
        return [r["id"] for r in cur.fetchall()]


def plan_week_rows(plan_id: int, week_number: int) -> List[Dict[str, Any]]:
    sql = """
    SELECT tpw.*, tw.week_number
    FROM training_plan_workouts tpw
    JOIN training_plan_weeks tw ON tw.id = tpw.week_id
    WHERE tw.plan_id = %s AND tw.week_number = %s
    ORDER BY tpw.day_of_week, tpw.id;
    """
    with conn_cursor() as (_, cur):
        cur.execute(sql, (plan_id, week_number))
        return list(cur.fetchall())


def get_active_plan() -> Optional[Dict[str, Any]]:
    sql = """
    SELECT id, start_date, weeks, is_active, created_at
    FROM training_plans
    WHERE is_active = true
    ORDER BY id DESC
    LIMIT 1;
    """
    with conn_cursor() as (_, cur):
        cur.execute(sql)
        row = cur.fetchone()
        return dict(row) if row else None


def get_week_ids_for_plan(plan_id: int) -> Dict[int, int]:
    """
    Return mapping week_number -> week_id for a given plan.
    """
    sql = "SELECT id, week_number FROM training_plan_weeks WHERE plan_id = %s;"
    out: Dict[int, int] = {}
    with conn_cursor() as (_, cur):
        cur.execute(sql, (plan_id,))
        for r in cur.fetchall():
            out[r["week_number"]] = r["id"]
    return out


# ---------------------------
# Writes and adjustments
# ---------------------------

def create_block_and_plan(start_date: date, weeks: int = 4) -> Tuple[int, List[int]]:
    """
    Create a training_blocks row and a new active training_plan with weeks 1..weeks.
    Returns (plan_id, [week_ids]).
    """
    end_date = date.fromordinal(start_date.toordinal() + weeks * 7 - 1)
    with conn_cursor() as (_, cur):
        # Insert block
        cur.execute(
            """
            INSERT INTO training_blocks(start_date, end_date, block_index)
            VALUES (%s, %s, (SELECT COALESCE(MAX(block_index), 0) + 1 FROM training_blocks))
            RETURNING id;
            """,
            (start_date, end_date),
        )
        _block_id = cur.fetchone()["id"]

        # Deactivate previous active and create new active plan
        cur.execute("UPDATE training_plans SET is_active = false WHERE is_active = true;")
        cur.execute(
            """
            INSERT INTO training_plans(start_date, weeks, is_active)
            VALUES (%s, %s, true)
            RETURNING id;
            """,
            (start_date, weeks),
        )
        plan_id = cur.fetchone()["id"]

        # Create week rows
        week_ids: List[int] = []
        for w in range(1, weeks + 1):
            cur.execute(
                "INSERT INTO training_plan_weeks(plan_id, week_number) VALUES (%s, %s) RETURNING id;",
                (plan_id, w),
            )
            week_ids.append(cur.fetchone()["id"])

        return plan_id, week_ids


def insert_workout(
    week_id: int,
    day_of_week: int,
    exercise_id: int,
    sets: int,
    reps: int,
    rir_cue: Optional[float],
    percent_1rm: Optional[float],
    target_weight_kg: Optional[float],
    scheduled_time: Optional[str],
    is_cardio: bool,
) -> None:
    sql = """
    INSERT INTO training_plan_workouts
      (week_id, day_of_week, exercise_id, sets, reps, rir, percent_1rm, target_weight_kg, scheduled_time, is_cardio)
    VALUES
      (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
    """
    with conn_cursor() as (_, cur):
        cur.execute(
            sql,
            (
                week_id,
                day_of_week,
                exercise_id,
                sets,
                reps,
                rir_cue,
                percent_1rm,
                target_weight_kg,
                scheduled_time,
                is_cardio,
            ),
        )


def apply_plan_backoff(week_id: int, set_multiplier: float, rir_increment: float) -> int:
    """
    Reduce sets and increase RIR cue for the given week, bounded by min 1 set.
    Returns the number of rows updated.
    """
    sql = """
    UPDATE training_plan_workouts
    SET
      sets = GREATEST(1, ROUND(sets * %s)::int),
      rir  = CASE WHEN rir IS NULL THEN %s ELSE rir + %s END
    WHERE week_id = %s AND is_cardio = false;
    """
    with conn_cursor() as (_, cur):
        cur.execute(sql, (set_multiplier, rir_increment, rir_increment, week_id))
        return cur.rowcount


def adjust_sets_only(week_id: int, set_multiplier: float) -> int:
    """
    Adjust sets up or down with bounding, without touching RIR.
    """
    sql = """
    UPDATE training_plan_workouts
    SET sets = GREATEST(1, ROUND(sets * %s)::int)
    WHERE week_id = %s AND is_cardio = false;
    """
    with conn_cursor() as (_, cur):
        cur.execute(sql, (set_multiplier, week_id))
        return cur.rowcount


def adjust_rir(week_id: int, rir_delta: float) -> int:
    """
    Adjust RIR cue for all non-cardio rows. If RIR is NULL and rir_delta > 0, set it to rir_delta.
    We avoid negative deltas when RIR is NULL to keep cues sensible.
    """
    sql = """
    UPDATE training_plan_workouts
    SET rir = CASE
                WHEN rir IS NULL AND %s > 0 THEN %s
                WHEN rir IS NULL AND %s <= 0 THEN NULL
                ELSE rir + %s
              END
    WHERE week_id = %s AND is_cardio = false;
    """
    with conn_cursor() as (_, cur):
        cur.execute(sql, (rir_delta, rir_delta, rir_delta, rir_delta, week_id))
        return cur.rowcount


def adjust_main_lifts_intensity(
    week_id: int,
    delta_percent_abs: float,
    main_lift_ids: Tuple[int, int, int, int],
    min_pct: float = 40.0,
    max_pct: float = 95.0,
) -> int:
    """
    Bounded absolute adjustment of percent_1rm for main lifts only.
    Also scales target_weight_kg proportionally when present.
    """
    sql = """
    UPDATE training_plan_workouts
    SET
      percent_1rm = LEAST(%s, GREATEST(%s, COALESCE(percent_1rm, 0) + %s)),
      target_weight_kg = CASE
        WHEN target_weight_kg IS NOT NULL AND percent_1rm IS NOT NULL AND percent_1rm <> 0
        THEN ROUND((target_weight_kg * (COALESCE(percent_1rm, 0) + %s) / percent_1rm)::numeric, 1)
        ELSE target_weight_kg
      END
    WHERE week_id = %s
      AND is_cardio = false
      AND exercise_id IN (%s, %s, %s, %s);
    """
    with conn_cursor() as (_, cur):
        cur.execute(
            sql,
            (max_pct, min_pct, delta_percent_abs, delta_percent_abs, week_id, *main_lift_ids),
        )
        return cur.rowcount


def log_wger_export(
    plan_id: int, week_number: int, payload: Dict[str, Any], response: Optional[Dict[str, Any]]
) -> None:
    """
    Persist the payload and response with an idempotency checksum.
    """
    body = json.dumps(payload, sort_keys=True)
    checksum = hashlib.sha1(f"{plan_id}:{week_number}:{body}".encode("utf-8")).hexdigest()
    with conn_cursor() as (_, cur):
        cur.execute(
            """
            INSERT INTO wger_export_log(plan_id, week_number, payload_json, response_json, checksum)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (plan_id, week_number, checksum) DO NOTHING;
            """,
            (plan_id, week_number, Json(payload), Json(response or {}), checksum),
        )
