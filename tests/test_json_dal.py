from datetime import date

from pete_e.config import settings
from pete_e.data_access.json_dal import JsonDal


def test_json_dal_roundtrip(tmp_path, monkeypatch):
    # Redirect settings paths to the temp directory
    monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path)
    dal = JsonDal()

    # Lift log entry
    dal.save_strength_log_entry(1, date(2024, 1, 1), 5, 100.0, 1)
    log = dal.load_lift_log()
    assert "1" in log and log["1"][0]["weight"] == 100.0

    # Daily summary
    summary = {"withings": {"weight": 80}, "apple": {"steps": 1000}}
    day = date(2024, 1, 1)
    dal.save_daily_summary(summary, day)
    assert dal.get_daily_summary(day) == summary

    history = dal.load_history()
    assert history[day.isoformat()] == summary

    metrics = dal.get_historical_metrics(1)
    assert metrics == [summary]

    data = dal.get_historical_data(day, day)
    assert data == [summary]
