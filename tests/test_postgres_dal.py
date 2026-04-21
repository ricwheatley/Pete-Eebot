import unittest
from datetime import date
from unittest.mock import patch, MagicMock

# Assuming your DAL is in this structure
from pete_e.infrastructure.postgres_dal import PostgresDal

class TestPostgresDal(unittest.TestCase):

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
    def test_get_core_pool_ids_reads_core_pool_table_when_present(self, mock_get_pool):
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()

        mock_get_pool.return_value = mock_pool
        mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchone.return_value = ("core_pool",)
        mock_cur.fetchall.return_value = [(101,), (102,)]

        dal = PostgresDal()
        result = dal.get_core_pool_ids()

        self.assertEqual(result, [101, 102])
        executed_sql = [call.args[0] for call in mock_cur.execute.call_args_list]
        self.assertIn("SELECT to_regclass('public.core_pool');", executed_sql)
        self.assertIn("SELECT exercise_id FROM core_pool ORDER BY exercise_id", executed_sql)

    @patch('pete_e.infrastructure.postgres_dal.get_pool')
    def test_get_core_pool_ids_falls_back_to_categories_without_core_pool(self, mock_get_pool):
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        first_cur = MagicMock()
        second_cur = MagicMock()

        mock_get_pool.return_value = mock_pool
        mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.side_effect = [
            MagicMock(__enter__=MagicMock(return_value=first_cur), __exit__=MagicMock(return_value=False)),
            MagicMock(__enter__=MagicMock(return_value=second_cur), __exit__=MagicMock(return_value=False)),
        ]
        first_cur.fetchone.return_value = (None,)
        second_cur.fetchall.return_value = [(201,), (202,)]

        dal = PostgresDal()
        result = dal.get_core_pool_ids()

        self.assertEqual(result, [201, 202])
        second_cur.execute.assert_called_once()
        self.assertIn("FROM wger_exercise ex", second_cur.execute.call_args.args[0])



if __name__ == '__main__':
    unittest.main()
