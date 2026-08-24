import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch, MagicMock

# Assuming your DAL is in this structure
from pete_e.infrastructure.postgres_dal import PostgresDal
from pete_e.domain.wger_workouts import WgerWorkoutSet

class TestPostgresDal(unittest.TestCase):

    @patch('pete_e.infrastructure.postgres_dal.get_pool')
    def test_reconcile_wger_logs_replaces_only_requested_window(self, mock_get_pool):
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_get_pool.return_value = mock_pool
        mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = [{"id": 615}]

        dal = PostgresDal()
        workout_set = WgerWorkoutSet(
            source_id="log-uuid",
            session_id="session-uuid",
            performed_at=datetime(2026, 8, 17, 8, tzinfo=timezone.utc),
            day=date(2026, 8, 17),
            exercise_id=615,
            set_number=1,
            reps=5,
            weight_kg=Decimal("100.000"),
            rir=2.0,
        )

        stored = dal.reconcile_wger_logs(
            start_date=date(2026, 8, 17),
            end_date=date(2026, 8, 23),
            workout_sets=[workout_set],
        )

        self.assertEqual(stored, 1)
        self.assertEqual(mock_cur.execute.call_args_list[1].args, (
            "DELETE FROM wger_logs WHERE date BETWEEN %s AND %s;",
            (date(2026, 8, 17), date(2026, 8, 23)),
        ))
        insert_sql, rows = mock_cur.executemany.call_args.args
        self.assertIn("wger_log_id", insert_sql)
        self.assertEqual(rows[0][0], date(2026, 8, 17))
        self.assertEqual(rows[0][6], "log-uuid")
        self.assertEqual(rows[0][7], "session-uuid")

    @patch('pete_e.infrastructure.postgres_dal.get_pool')
    def test_reconcile_wger_logs_validates_catalogue_before_delete(self, mock_get_pool):
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_get_pool.return_value = mock_pool
        mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = []
        dal = PostgresDal()
        workout_set = WgerWorkoutSet(
            source_id="log-uuid",
            session_id=None,
            performed_at=datetime(2026, 8, 17, 8, tzinfo=timezone.utc),
            day=date(2026, 8, 17),
            exercise_id=9999,
            set_number=1,
            reps=5,
            weight_kg=None,
            rir=None,
        )

        with self.assertRaisesRegex(ValueError, "catalogue is missing exercise"):
            dal.reconcile_wger_logs(
                start_date=date(2026, 8, 17),
                end_date=date(2026, 8, 23),
                workout_sets=[workout_set],
            )

        self.assertEqual(mock_cur.execute.call_count, 1)
        mock_cur.executemany.assert_not_called()

    @patch('pete_e.infrastructure.postgres_dal.get_pool')
    def test_save_withings_daily(self, mock_get_pool):
        """Test that save_withings_daily executes the correct SQL."""
        # 1. Create mocks for the pool, connection, and cursor
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()

        # 2. Configure the mock pool to be returned by get_pool
        mock_get_pool.return_value = mock_pool

        # 3. Configure the nested context managers
        mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        # 4. Now, when we create the DAL, it will use our mock pool
        dal = PostgresDal()
        test_date = date(2025, 1, 15)
        
        # 5. Call the method being tested
        dal.save_withings_daily(test_date, 75.5, 22.1, 41.5, 55.0)

        # 6. Assert that the SQL execution was called
        mock_get_pool.assert_called_once()
        mock_pool.connection.assert_called_once()
        mock_conn.cursor.assert_called_once()
        mock_cur.execute.assert_called_once()
        sql_text, params = mock_cur.execute.call_args.args
        self.assertIn("metabolic_age_years", sql_text)
        self.assertEqual(len(params), 14)

    @patch('pete_e.infrastructure.postgres_dal.get_pool')
    def test_save_withings_measure_groups(self, mock_get_pool):
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()

        mock_get_pool.return_value = mock_pool
        mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        dal = PostgresDal()
        dal.save_withings_measure_groups(
            day=date(2026, 4, 13),
            measure_groups=[
                {
                    "grpid": 7614618991,
                    "date": 1776051256,
                    "created": 1776051318,
                    "modified": 1776051318,
                    "category": 1,
                    "attrib": 0,
                    "comment": None,
                    "deviceid": "device-1",
                    "hash_deviceid": "device-1",
                    "model": "Body Comp",
                    "modelid": 18,
                    "timezone": "Europe/London",
                    "measures": [{"type": 1, "value": 92891, "unit": -3}],
                }
            ],
        )

        mock_cur.executemany.assert_called_once()
        sql_text = mock_cur.executemany.call_args.args[0]
        self.assertIn("INSERT INTO withings_measure_groups", sql_text)
        values = mock_cur.executemany.call_args.args[1]
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0][0], 7614618991)
        """Perform test save withings measure groups."""

    @patch('pete_e.infrastructure.postgres_dal.get_pool')
    def test_insert_nutrition_log_returns_inserted_row(self, mock_get_pool):
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()

        mock_get_pool.return_value = mock_pool
        mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchone.return_value = {
            "id": 1,
            "protein_g": 40,
            "duplicate": False,
        }

        dal = PostgresDal()
        row, duplicate = dal.insert_nutrition_log(
            {
                "client_event_id": "evt-1",
                "dedupe_fingerprint": "abc",
                "eaten_at": "2026-05-05T12:30:00Z",
                "local_date": date(2026, 5, 5),
                "protein_g": 40,
                "carbs_g": 65,
                "fat_g": 18,
                "alcohol_g": 10,
                "fiber_g": 7,
                "estimated_total_calories": 700,
                "calories_est": 582,
                "source": "photo_estimate",
                "context": "post_run",
                "confidence": "medium",
                "meal_label": None,
                "notes": None,
                "raw_payload_json": {"protein_g": 40},
            }
        )

        self.assertFalse(duplicate)
        self.assertEqual(row["id"], 1)
        sql_text = mock_cur.execute.call_args.args[0]
        self.assertIn("INSERT INTO nutrition_log", sql_text)
        self.assertIn("ON CONFLICT DO NOTHING", sql_text)

    @patch('pete_e.infrastructure.postgres_dal.get_pool')
    def test_get_nutrition_daily_summary_queries_log_table(self, mock_get_pool):
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()

        mock_get_pool.return_value = mock_pool
        mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchone.return_value = {"meals_logged": 0}

        dal = PostgresDal()
        result = dal.get_nutrition_daily_summary(date(2026, 5, 5))

        self.assertEqual(result["meals_logged"], 0)
        sql_text = mock_cur.execute.call_args.args[0]
        self.assertIn("FROM nutrition_log", sql_text)
        self.assertEqual(mock_cur.execute.call_args.args[1], (date(2026, 5, 5), date(2026, 5, 5)))


    @patch('pete_e.infrastructure.postgres_dal.get_pool')
    def test_get_historical_data(self, mock_get_pool):
        """Test that get_historical_data queries the daily_summary table."""
        # 1. Create mocks for the pool, connection, and cursor
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()

        # 2. Configure the mock pool to be returned by get_pool
        mock_get_pool.return_value = mock_pool

        # 3. Configure the nested context managers
        # pool.connection() -> conn
        mock_pool.connection.return_value.__enter__.return_value = mock_conn
        # conn.cursor() -> cur
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        
        # 4. Set the return value for the database call
        mock_cur.fetchall.return_value = [{"date": "2025-01-15", "steps": 5000}]

        # 5. Now, when we create the DAL, it will use our mock pool
        dal = PostgresDal()
        start = date(2025, 1, 1)
        end = date(2025, 1, 31)
        result = dal.get_historical_data(start, end)

        # 6. Assertions remain the same
        mock_get_pool.assert_called_once()
        mock_cur.execute.assert_called_once()
        self.assertEqual(result, [{"date": "2025-01-15", "steps": 5000}])

    @patch('pete_e.infrastructure.postgres_dal.get_pool')
    def test_refresh_daily_summary_refreshes_inputs_before_body_age(self, mock_get_pool):
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()

        mock_get_pool.return_value = mock_pool
        mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        dal = PostgresDal()
        dal.refresh_daily_summary(days=7)

        statements = [call.args[0] for call in mock_cur.execute.call_args_list]
        self.assertEqual(
            statements,
            [
                "SELECT sp_refresh_daily_summary(%s, %s);",
                "SELECT sp_upsert_body_age_range(%s, %s, %s);",
                "SELECT sp_refresh_daily_summary(%s, %s);",
            ],
        )
        """Perform test refresh daily summary refreshes inputs before body age."""


    @patch('pete_e.infrastructure.postgres_dal.get_pool')
    def test_get_assistance_candidates_uses_programming_metadata(self, mock_get_pool):
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()

        mock_get_pool.return_value = mock_pool
        mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchone.return_value = ("exercise_programming_metadata",)
        mock_cur.fetchall.return_value = [
            {"exercise_id": 201, "difficulty": 1},
            {"exercise_id": 202, "difficulty": 2},
        ]

        dal = PostgresDal()
        result = dal.get_assistance_candidates_for(615, max_difficulty=2)

        self.assertEqual(
            result,
            [
                {"exercise_id": 201, "difficulty": 1},
                {"exercise_id": 202, "difficulty": 2},
            ],
        )
        self.assertEqual(mock_cur.execute.call_args.args[1], (2,))
        """Perform test get assistance candidates uses programming metadata."""

    @patch('pete_e.infrastructure.postgres_dal.get_pool')
    def test_get_assistance_candidates_falls_back_to_curated_defaults_without_metadata(self, mock_get_pool):
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()

        mock_get_pool.return_value = mock_pool
        mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchone.return_value = (None,)

        dal = PostgresDal()
        result = dal.get_assistance_candidates_for(615, max_difficulty=2)

        self.assertEqual(
            result,
            [
                {"exercise_id": 46, "difficulty": 2},
                {"exercise_id": 1366, "difficulty": 2},
            ],
        )
        """Perform test get assistance candidates falls back to curated defaults without metadata."""

    @patch('pete_e.infrastructure.postgres_dal.get_pool')
    def test_wger_reference_upserts_use_bulk_upsert(self, mock_get_pool):
        mock_pool = MagicMock()
        mock_get_pool.return_value = mock_pool

        dal = PostgresDal()
        dal._bulk_upsert = MagicMock()

        dal.upsert_wger_categories(
            [
                {"id": 10, "name": "Strength"},
                {"id": None, "name": "Ignored"},
            ]
        )
        dal.upsert_wger_equipment(
            [
                {"id": 8, "name": "Dumbbell"},
                {"id": 9, "name": ""},
            ]
        )
        dal.upsert_wger_muscles(
            [
                {"id": 1, "name": "Biceps brachii", "name_en": "Biceps", "is_front": True},
                {"id": 2, "name": None},
            ]
        )

        self.assertEqual(dal._bulk_upsert.call_args_list[0].args, (
            "wger_category",
            [{"id": 10, "name": "Strength"}],
            ["id"],
            ["name"],
        ))
        self.assertEqual(dal._bulk_upsert.call_args_list[1].args, (
            "wger_equipment",
            [{"id": 8, "name": "Dumbbell"}],
            ["id"],
            ["name"],
        ))
        self.assertEqual(dal._bulk_upsert.call_args_list[2].args, (
            "wger_muscle",
            [{"id": 1, "name": "Biceps brachii", "name_en": "Biceps", "is_front": True}],
            ["id"],
            ["name", "name_en", "is_front"],
        ))
        """Perform test wger reference upserts use bulk upsert."""

    @patch('pete_e.infrastructure.postgres_dal.get_pool')
    def test_get_core_candidates_uses_programming_metadata(self, mock_get_pool):
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()

        mock_get_pool.return_value = mock_pool
        mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchone.return_value = ("exercise_programming_metadata",)
        mock_cur.fetchall.return_value = [
            {"exercise_id": 458, "difficulty": 1},
            {"exercise_id": 500, "difficulty": 2},
        ]

        dal = PostgresDal()
        result = dal.get_core_candidates(max_difficulty=2)

        self.assertEqual(
            result,
            [
                {"exercise_id": 458, "difficulty": 1},
                {"exercise_id": 500, "difficulty": 2},
            ],
        )
        self.assertEqual(mock_cur.execute.call_args.args[1], (2,))
        """Perform test get core candidates uses programming metadata."""

    @patch('pete_e.infrastructure.postgres_dal.get_pool')
    def test_get_core_candidates_falls_back_to_curated_defaults_without_metadata(self, mock_get_pool):
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()

        mock_get_pool.return_value = mock_pool
        mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchone.return_value = (None,)

        dal = PostgresDal()
        result = dal.get_core_candidates(max_difficulty=2)

        self.assertEqual(
            result,
            [
                {"exercise_id": 458, "difficulty": 1},
                {"exercise_id": 1001, "difficulty": 1},
                {"exercise_id": 500, "difficulty": 2},
                {"exercise_id": 580, "difficulty": 2},
            ],
        )
        """Perform test get core candidates falls back to curated defaults without metadata."""

    @patch('pete_e.infrastructure.postgres_dal.get_pool')
    def test_seed_main_lifts_and_assistance_disables_stale_pool_rows(self, mock_get_pool):
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()

        mock_get_pool.return_value = mock_pool
        mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        dal = PostgresDal()
        dal.seed_main_lifts_and_assistance([615], [(615, [(46, 5), (373, 0)])])

        executed_sql = [call.args[0] for call in mock_cur.execute.call_args_list]
        self.assertIn(
            "UPDATE assistance_pool SET difficulty = 0 WHERE main_exercise_id = ANY(%s)",
            executed_sql,
        )
        values = mock_cur.executemany.call_args_list[0].args[1]
        self.assertEqual(values, [(615, 46, 5), (615, 373, 0)])
        """Perform test seed main lifts and assistance disables stale pool rows."""

    @patch('pete_e.infrastructure.postgres_dal.get_pool')
    def test_seed_main_lifts_passes_tuple_ids_as_postgres_array(self, mock_get_pool):
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()

        mock_get_pool.return_value = mock_pool
        mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        dal = PostgresDal()
        dal.seed_main_lifts((615, 73, 184, 566))

        self.assertEqual(mock_cur.execute.call_args.args[1], ([615, 73, 184, 566],))
        """Perform test seed main lifts passes tuple ids as postgres array."""

    @patch('pete_e.infrastructure.postgres_dal.get_pool')
    def test_seed_core_pool_inserts_existing_default_ids(self, mock_get_pool):
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()

        mock_get_pool.return_value = mock_pool
        mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        dal = PostgresDal()
        dal.seed_core_pool([458, 500])

        mock_cur.execute.assert_called_once()
        sql_text, params = mock_cur.execute.call_args.args
        self.assertIn("INSERT INTO core_pool", sql_text)
        self.assertIn("WHERE id = ANY(%s)", sql_text)
        self.assertEqual(params, ([458, 500],))
        """Perform test seed core pool inserts existing default ids."""

    @patch('pete_e.infrastructure.postgres_dal.get_pool')
    def test_seed_programming_metadata_inserts_missing_rows_only(self, mock_get_pool):
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()

        mock_get_pool.return_value = mock_pool
        mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        dal = PostgresDal()
        dal.seed_exercise_programming_metadata([458, 1409])

        sql_text, params = mock_cur.execute.call_args.args
        self.assertIn("INSERT INTO exercise_programming_metadata", sql_text)
        self.assertIn("ON CONFLICT (exercise_id) DO NOTHING", sql_text)
        self.assertEqual(params, ([458, 1409],))
        """Perform test seed programming metadata inserts missing rows only."""

    def test_difficulty_cap_stays_at_two_without_sufficient_evidence(self):
        dal = PostgresDal(pool=MagicMock())
        evidence = {
            "strength_history_days": 364,
            "completed_sessions": 24,
            "completion_ratio": 0.9,
            "nondeclining_exercise_count": 3,
        }

        self.assertEqual(dal._next_exercise_difficulty_cap(2, evidence), 2)
        """Perform test difficulty cap stays at two without sufficient evidence."""

    def test_difficulty_cap_unlocks_to_three_with_sufficient_evidence(self):
        dal = PostgresDal(pool=MagicMock())
        evidence = {
            "strength_history_days": 365,
            "completed_sessions": 24,
            "completion_ratio": 0.75,
            "nondeclining_exercise_count": 3,
        }

        self.assertEqual(dal._next_exercise_difficulty_cap(2, evidence), 3)
        """Perform test difficulty cap unlocks to three with sufficient evidence."""

    def test_difficulty_cap_rises_one_level_after_introduction_window(self):
        dal = PostgresDal(pool=MagicMock())
        evidence = {
            "days_since_last_unlock": 56,
            "completed_sessions_at_current_cap": 8,
            "completion_ratio": 0.8,
        }

        self.assertEqual(dal._next_exercise_difficulty_cap(3, evidence), 4)
        """Perform test difficulty cap rises one level after introduction window."""

    @patch('pete_e.infrastructure.postgres_dal.get_pool')
    def test_get_plan_week_rows_includes_catalogue_exercise_name(self, mock_get_pool):
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()

        mock_get_pool.return_value = mock_pool
        mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = []

        dal = PostgresDal()
        dal.get_plan_week_rows(plan_id=42, week_number=1)

        executed_sql = mock_cur.execute.call_args.args[0]
        self.assertIn("ex.name AS exercise_name", executed_sql)
        self.assertIn("LEFT JOIN wger_exercise ex ON ex.id = tpw.exercise_id", executed_sql)
        """Perform test get plan week rows includes catalogue exercise name."""
    """Represent TestPostgresDal."""



if __name__ == '__main__':
    unittest.main()
