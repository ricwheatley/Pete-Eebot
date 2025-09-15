import unittest
from datetime import date
from unittest.mock import patch, MagicMock

# Assuming your DAL is in this structure
from pete_e.data_access.postgres_dal import PostgresDal

class TestPostgresDal(unittest.TestCase):

    @patch('pete_e.data_access.postgres_dal.get_conn')
    def test_save_withings_daily(self, mock_get_conn):
        """Test that save_withings_daily executes the correct SQL."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cur

        dal = PostgresDal()
        test_date = date(2025, 1, 15)
        dal.save_withings_daily(test_date, 75.5, 22.1)

        self.assertTrue(mock_cur.execute.called)
        # Check that the SQL statement contains the key parts
        sql_call = mock_cur.execute.call_args[0][0]
        self.assertIn("INSERT INTO withings_daily", sql_call)
        self.assertIn("ON CONFLICT (date) DO UPDATE", sql_call)
        
        # Check that the correct data was passed
        data_tuple = mock_cur.execute.call_args[0][1]
        self.assertEqual(data_tuple, (test_date, 75.5, 22.1))


    @patch('pete_e.data_access.postgres_dal.get_conn')
    def test_get_historical_data(self, mock_get_conn):
        """Test that get_historical_data queries the daily_summary view."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cur
        mock_cur.fetchall.return_value = [{"date": "2025-01-15", "steps": 5000}]

        dal = PostgresDal()
        start = date(2025, 1, 1)
        end = date(2025, 1, 31)
        result = dal.get_historical_data(start, end)

        self.assertTrue(mock_cur.execute.called)
        sql_call = mock_cur.execute.call_args[0][0]
        self.assertIn("SELECT * FROM daily_summary", sql_call)
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['steps'], 5000)


if __name__ == '__main__':
    unittest.main()