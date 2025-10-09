import unittest
from datetime import date
from unittest.mock import patch, MagicMock
import pete_e.infrastructure.postgres_dal as postgres_dal

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



if __name__ == '__main__':
    unittest.main()
