# pete_e/infrastructure/apple_writer.py

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

import psycopg
from psycopg import sql

from pete_e.config.config import settings
from pete_e.infrastructure.database import get_conn
from pete_e.infrastructure.apple_parser import (
    DailyHeartRateSummary,
    DailyMetricPoint,
    DailySleepSummary,
    WorkoutEnergyPoint,
    WorkoutHeader,
    WorkoutHRPoint,
    WorkoutHRRecoveryPoint,
    WorkoutStepsPoint,
)

from pete_e.infrastructure import log_utils


class AppleHealthWriter:
    """Persists parsed Apple Health data into Postgres using efficient bulk upserts."""

    def __init__(self, conn: psycopg.Connection):
        self.conn = conn
        self._device_cache: Dict[str, int] = {}
        self._metric_type_cache: Dict[str, int] = {}
        self._workout_type_cache: Dict[str, int] = {}

    def _ensure_ids_cached(self, data: dict) -> None:
        """Efficiently pre-fetches all required device and type IDs."""
        devices = {d for d in data["devices"]}
        metric_types = {m for m in data["metric_types"]}
        workout_types = {w for w in data["workout_types"]}

        if not devices and not metric_types and not workout_types:
            return

        log_utils.info("Caching reference IDs for devices and types...")
        with self.conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            if devices:
                cur.execute('SELECT name, device_id FROM "Device" WHERE name = ANY(%s)', [list(devices)])
                self._device_cache.update({r["name"]: r["device_id"] for r in cur})
            if metric_types:
                cur.execute('SELECT name, metric_id FROM "MetricType" WHERE name = ANY(%s)', [list(metric_types)])
                self._metric_type_cache.update({r["name"]: r["metric_id"] for r in cur})
            if workout_types:
                cur.execute('SELECT name, type_id FROM "WorkoutType" WHERE name = ANY(%s)', [list(workout_types)])
                self._workout_type_cache.update({r["name"]: r["type_id"] for r in cur})

    def _ensure_ref_item(self, table: str, key_col: str, val_col: str, key: str, cache: dict, **kwargs) -> int:
        """Generic helper to find or create a reference item (e.g., Device, MetricType)."""
        if key in cache:
            return cache[key]

        log_utils.info(f"Creating new entry in \"{table}\" for '{key}'")
        cols = [key_col] + list(kwargs.keys())
        vals = [key] + list(kwargs.values())
        
        stmt = sql.SQL("""
            INSERT INTO {table} ({cols}) VALUES ({placeholders})
            ON CONFLICT ({key_col}) DO UPDATE SET {key_col} = EXCLUDED.{key_col}
            RETURNING {val_col}
        """).format(
            table=sql.Identifier(table),
            cols=sql.SQL(",").join(map(sql.Identifier, cols)),
            placeholders=sql.SQL(",").join(sql.Placeholder() * len(cols)),
            key_col=sql.Identifier(key_col),
            val_col=sql.Identifier(val_col),
        )

        with self.conn.cursor() as cur:
            cur.execute(stmt, vals)
            item_id = cur.fetchone()[0]
            cache[key] = item_id
            return item_id

    def get_last_import_timestamp(self) -> Optional[datetime]:
        """
        Retrieves the timestamp of the most recently processed file from the ImportLog.
        Returns None if no imports have occurred yet. The returned datetime is
        guaranteed to be timezone-aware (UTC).
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT last_file_processed_at FROM "ImportLog"
                ORDER BY import_timestamp DESC
                LIMIT 1
            """)
            result = cur.fetchone()
            if not result:
                return None

            last_ts = result[0]

            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)
            
            return last_ts

    def save_last_import_timestamp(self, latest_file_timestamp: datetime) -> None:
        """Saves a record of this import run, logging the timestamp of the newest file."""
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO "ImportLog" (last_file_processed_at) VALUES (%s)
            """, (latest_file_timestamp,))
        log_utils.info(f"Saved new import checkpoint with timestamp: {latest_file_timestamp}")


    def _execute_many_upsert(self, table: str, conflict_keys: List[str], update_keys: List[str], data: List[dict]):
        """A generic, high-performance bulk upsert function."""
        if not data:
            return

        cols = list(data[0].keys())
        placeholders = sql.SQL(",").join(sql.Placeholder() * len(cols))

        if update_keys:
            conflict_action = sql.SQL("DO UPDATE SET {update_clause}").format(
                update_clause=sql.SQL(",").join(
                    sql.SQL("{} = EXCLUDED.{}").format(sql.Identifier(k), sql.Identifier(k)) for k in update_keys
                )
            )
        else:
            conflict_action = sql.SQL("DO NOTHING")

        stmt = sql.SQL("""
            INSERT INTO {table} ({cols})
            VALUES ({placeholders})
            ON CONFLICT ({conflict_keys}) {conflict_action}
        """).format(
            table=sql.Identifier(table),
            cols=sql.SQL(",").join(map(sql.Identifier, cols)),
            placeholders=placeholders,
            conflict_keys=sql.SQL(",").join(map(sql.Identifier, conflict_keys)),
            conflict_action=conflict_action,
        )
        
        values = [[row[c] for c in cols] for row in data]
        
        with self.conn.cursor() as cur:
            cur.executemany(stmt, values)
            log_utils.info(f"Upserted {len(data)} rows into \"{table}\".")

    def _prepare_data_for_bulk_upsert(self, parsed_data: dict):
        """Pre-fetches all foreign key IDs to avoid row-by-row lookups."""
        unique_devices = {p.device_name for p in parsed_data["daily_metric_points"]}
        unique_devices.update(s.device_name for s in parsed_data["hr_summaries"])
        unique_devices.update(s.device_name for s in parsed_data["sleep_summaries"])
        unique_devices.update(w.device_name for w in parsed_data["workout_headers"])

        unique_metric_types = {(p.metric_name, p.unit) for p in parsed_data["daily_metric_points"]}
        unique_workout_types = {w.type_name for w in parsed_data["workout_headers"]}

        for name in unique_devices:
            self._ensure_ref_item("Device", "name", "device_id", name, self._device_cache)
        for name, unit in unique_metric_types:
            self._ensure_ref_item("MetricType", "name", "metric_id", name, self._metric_type_cache, unit=unit)
        for name in unique_workout_types:
            self._ensure_ref_item("WorkoutType", "name", "type_id", name, self._workout_type_cache)
            
    def _utc_to_naive(self, dt: datetime) -> datetime:
        """Safely converts a timezone-aware datetime to a naive UTC datetime."""
        if dt.tzinfo is None:
            return dt
        return dt.astimezone(timezone.utc).replace(tzinfo=None)

    def upsert_all(self, parsed_data: dict) -> None:
        """Main entrypoint to upsert all parsed data in efficient batches."""
        self._prepare_data_for_bulk_upsert(parsed_data)

        daily_metrics_data = [
          {
              "metric_id": self._metric_type_cache[p.metric_name],
              "device_id": self._device_cache[p.device_name],
              "date": p.date, 
              "value": p.value,
          }
          for p in parsed_data["daily_metric_points"]
        ]
        self._execute_many_upsert("DailyMetric", ["metric_id", "device_id", "date"], ["value"], daily_metrics_data)

        hr_summary_data = [
            {
                "device_id": self._device_cache[s.device_name],
                "date": s.date.date(),
                "hr_min": s.hr_min, "hr_avg": s.hr_avg, "hr_max": s.hr_max
            }
            for s in parsed_data["hr_summaries"]
        ]
        self._execute_many_upsert("DailyHeartRateSummary", ["device_id", "date"], ["hr_min", "hr_avg", "hr_max"], hr_summary_data)

        sleep_summary_data = [
            {
                "device_id": self._device_cache[s.device_name],
                "date": s.date.date(),
                "sleep_start": self._utc_to_naive(s.sleep_start),
                "sleep_end": self._utc_to_naive(s.sleep_end),
                "in_bed_start": self._utc_to_naive(s.in_bed_start) if s.in_bed_start else None,
                "in_bed_end": self._utc_to_naive(s.in_bed_end) if s.in_bed_end else None,
                "total_sleep_hrs": s.total_sleep_hrs, "core_hrs": s.core_hrs, "deep_hrs": s.deep_hrs,
                "rem_hrs": s.rem_hrs, "awake_hrs": s.awake_hrs
            }
            for s in parsed_data["sleep_summaries"]
        ]
        update_cols = ["sleep_start", "sleep_end", "in_bed_start", "in_bed_end", "total_sleep_hrs", "core_hrs", "deep_hrs", "rem_hrs", "awake_hrs"]
        self._execute_many_upsert("DailySleepSummary", ["device_id", "date"], update_cols, sleep_summary_data)

        workout_header_data = [
            {
                "workout_id": w.workout_id,
                "type_id": self._workout_type_cache[w.type_name],
                "device_id": self._device_cache[w.device_name],
                "start_time": self._utc_to_naive(w.start_time),
                "end_time": self._utc_to_naive(w.end_time),
                "duration_sec": w.duration_sec, "location": w.location, "total_distance_km": w.total_distance_km,
                "total_active_energy_kj": w.total_active_energy_kj, "avg_intensity": w.avg_intensity,
                "elevation_gain_m": w.elevation_gain_m,
                "environment_temp_degc": w.environment_temp_degc,
                "environment_humidity_percent": w.environment_humidity_percent
            }
            for w in parsed_data["workout_headers"]
        ]
        update_cols = ["type_id", "device_id", "start_time", "end_time", "duration_sec", "location", "total_distance_km", "total_active_energy_kj", "avg_intensity", "elevation_gain_m", "environment_temp_degc", "environment_humidity_percent"]
        self._execute_many_upsert("Workout", ["workout_id"], update_cols, workout_header_data)

        self._execute_many_upsert("WorkoutHeartRate", ["workout_id", "offset_sec"], ["hr_min", "hr_avg", "hr_max"], [asdict(p) for p in parsed_data["workout_hr"]])
        self._execute_many_upsert("WorkoutStepCount", ["workout_id", "offset_sec"], ["steps"], [asdict(p) for p in parsed_data["workout_steps"]])
        self._execute_many_upsert("WorkoutActiveEnergy", ["workout_id", "offset_sec"], ["energy_kcal"], [asdict(p) for p in parsed_data["workout_energy"]])
        self._execute_many_upsert("WorkoutHeartRateRecovery", ["workout_id", "offset_sec"], ["hr_min", "hr_avg", "hr_max"], [asdict(p) for p in parsed_data["workout_hr_recovery"]])

        # After inserting granular data, calculate and update totals where they were NULL.
        workout_ids_in_batch = [w['workout_id'] for w in workout_header_data]
        if not workout_ids_in_batch:
            return

        with self.conn.cursor() as cur:
            log_utils.info(f"Calculating and backfilling summary data for {len(workout_ids_in_batch)} workout(s)...")
            
            # Calculate and update total active energy
            update_energy_stmt = sql.SQL("""
                UPDATE "Workout" w
                SET total_active_energy_kj = COALESCE(w.total_active_energy_kj, sub.calculated_kj)
                FROM (
                    SELECT workout_id, SUM(energy_kcal) * 4.184 AS calculated_kj
                    FROM "WorkoutActiveEnergy"
                    WHERE workout_id = ANY(%s)
                    GROUP BY workout_id
                ) AS sub
                WHERE w.workout_id = sub.workout_id AND w.total_active_energy_kj IS NULL;
            """)
            cur.execute(update_energy_stmt, (workout_ids_in_batch,))
            log_utils.info(f"Updated total active energy for {cur.rowcount} workout(s).")
            
            # Calculate and update total distance from granular metrics
            update_distance_stmt = sql.SQL("""
                UPDATE "Workout" w
                SET total_distance_km = COALESCE(w.total_distance_km, sub.calculated_km)
                FROM (
                    SELECT
                        w_sub.workout_id,
                        SUM(dm.value) AS calculated_km
                    FROM "Workout" AS w_sub
                    JOIN "DailyMetric" AS dm ON dm.date >= w_sub.start_time AND dm.date < w_sub.end_time
                    JOIN "MetricType" AS mt ON dm.metric_id = mt.metric_id
                    WHERE
                        mt.name = 'distance_walking_running'
                        AND w_sub.workout_id = ANY(%s)
                    GROUP BY
                        w_sub.workout_id
                ) AS sub
                WHERE
                    w.workout_id = sub.workout_id AND w.total_distance_km IS NULL;
            """)
            cur.execute(update_distance_stmt, (workout_ids_in_batch,))
            log_utils.info(f"Updated total distance for {cur.rowcount} workout(s).")
