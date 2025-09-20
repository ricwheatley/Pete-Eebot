# pete_e/infrastructure/wger_writer.py

import logging
from typing import Dict, List

import psycopg
from psycopg import sql


class WgerWriter:
    """Persists parsed WGER catalogue data into Postgres using efficient bulk upserts."""

    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def _execute_many_upsert(self, table: str, conflict_keys: List[str], update_keys: List[str], data: List[Dict]):
        """A generic, high-performance bulk upsert function for psycopg 3."""
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

        values = [[row.get(c) for c in cols] for row in data]

        with self.conn.cursor() as cur:
            cur.executemany(stmt, values)
            logging.info(f"Upserted {len(data)} rows into \"{table}\".")

    def upsert_categories(self, categories: List[Dict]):
        """Upserts a list of exercise categories."""
        if not categories:
            return
        
        data_to_insert = [{"id": c.get("id"), "name": c.get("name")} for c in categories]
        self._execute_many_upsert("wger_category", ["id"], ["name"], data_to_insert)

    def upsert_equipment(self, equipment: List[Dict]):
        """Upserts a list of equipment types."""
        if not equipment:
            return

        data_to_insert = [{"id": e.get("id"), "name": e.get("name")} for e in equipment]
        self._execute_many_upsert("wger_equipment", ["id"], ["name"], data_to_insert)

    def upsert_muscles(self, muscles: List[Dict]):
        """Upserts a list of muscles."""
        if not muscles:
            return

        data_to_insert = [
            {
                "id": m.get("id"),
                "name": m.get("name"),
                "name_en": m.get("name_en"),
                "is_front": m.get("is_front"),
            }
            for m in muscles
        ]
        
        self._execute_many_upsert(
            "wger_muscle", 
            ["id"], 
            ["name", "name_en", "is_front"], 
            data_to_insert
        )

    def upsert_exercises(self, exercises: List[Dict]):
        """Upserts exercises and their many-to-many relationships."""
        if not exercises:
            return

        # 1. Upsert core exercise data
        exercise_data = [
            {
                "id": ex["id"],
                "uuid": ex["uuid"],
                "name": ex["name"],
                "description": ex["description"],
                "category_id": ex["category_id"],
            }
            for ex in exercises
        ]
        update_cols = ["uuid", "name", "description", "category_id"]
        self._execute_many_upsert("wger_exercise", ["id"], update_cols, exercise_data)

        # 2. Handle many-to-many relationships (equipment, muscles)
        equipment_links = []
        primary_muscle_links = []
        secondary_muscle_links = []
        exercise_ids = [ex["id"] for ex in exercises]

        for ex in exercises:
            ex_id = ex["id"]
            for eq_id in ex["equipment_ids"]:
                equipment_links.append({"exercise_id": ex_id, "equipment_id": eq_id})
            for m_id in ex["primary_muscle_ids"]:
                primary_muscle_links.append({"exercise_id": ex_id, "muscle_id": m_id})
            for m_id in ex["secondary_muscle_ids"]:
                secondary_muscle_links.append({"exercise_id": ex_id, "muscle_id": m_id})

        with self.conn.cursor() as cur:
            logging.info(f"Refreshing relationships for {len(exercise_ids)} exercises...")
            cur.execute('DELETE FROM wger_exercise_equipment WHERE exercise_id = ANY(%s)', (exercise_ids,))
            cur.execute('DELETE FROM wger_exercise_muscle_primary WHERE exercise_id = ANY(%s)', (exercise_ids,))
            cur.execute('DELETE FROM wger_exercise_muscle_secondary WHERE exercise_id = ANY(%s)', (exercise_ids,))

        # 3. Bulk insert new relationships
        if equipment_links:
            self._execute_many_upsert("wger_exercise_equipment", ["exercise_id", "equipment_id"], [], equipment_links)
        if primary_muscle_links:
            self._execute_many_upsert("wger_exercise_muscle_primary", ["exercise_id", "muscle_id"], [], primary_muscle_links)
        if secondary_muscle_links:
            self._execute_many_upsert("wger_exercise_muscle_secondary", ["exercise_id", "muscle_id"], [], secondary_muscle_links)

