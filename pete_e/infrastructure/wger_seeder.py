# pete_e/infrastructure/wger_seeder.py

from typing import List, Tuple

import psycopg

from pete_e.infrastructure import log_utils

# British English comments and docstrings.

# Static data for main lifts and their assistance exercises.
# Format: (main_lift_id, [assistance_lift_id_1, assistance_lift_id_2, ...])
ASSISTANCE_POOL_DATA: List[Tuple[int, List[int]]] = [
    # Squat (ID: 615)
    (615, [981, 977, 46, 984, 986, 987, 988, 989, 909, 910, 901, 265, 371, 632]),
    # Bench Press (ID: 73)
    (73, [83, 81, 923, 154, 475, 194, 197, 538, 537, 445, 498, 386]),
    # Deadlift (ID: 184)
    (184, [507, 189, 484, 627, 630, 294, 365, 366, 364, 301, 636, 960, 448]),
    # Overhead Press (ID: 566)
    (566, [20, 79, 348, 256, 822, 829, 282, 694, 693, 571, 572, 915, 478]),
]

MAIN_LIFT_IDS = [pool[0] for pool in ASSISTANCE_POOL_DATA]


class WgerSeeder:
    """Handles the one-time seeding of main lifts and assistance pools."""

    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def seed_main_lifts_and_assistance_pools(self):
        """
        Idempotently marks main lifts and inserts assistance pool relationships.
        This should be run after the WGER catalogue is populated.
        """
        log_utils.info("Seeding main lifts and assistance pools...")
        with self.conn.cursor() as cur:
            # 1. Mark the main lifts
            log_utils.info(f"Marking {len(MAIN_LIFT_IDS)} exercises as main lifts.")
            cur.execute(
                'UPDATE wger_exercise SET is_main_lift = true WHERE id = ANY(%s)',
                (MAIN_LIFT_IDS,)
            )

            # 2. Prepare and insert assistance pool data
            assistance_values = []
            for main_id, assistance_ids in ASSISTANCE_POOL_DATA:
                for assist_id in assistance_ids:
                    assistance_values.append((main_id, assist_id))
            
            if not assistance_values:
                log_utils.warn("No assistance pool data to seed.")
                return

            log_utils.info(f"Upserting {len(assistance_values)} assistance pool relationships.")
            # Use executemany for efficient batch insertion
            from psycopg import sql
            stmt = sql.SQL("""
                INSERT INTO assistance_pool (main_exercise_id, assistance_exercise_id)
                VALUES (%s, %s)
                ON CONFLICT (main_exercise_id, assistance_exercise_id) DO NOTHING
            """)
            cur.executemany(stmt, assistance_values)
        
        log_utils.info("Seeding complete.")
