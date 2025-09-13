import json
from datetime import date
from typing import Any, Dict, List

from pete_e.config import settings
from pete_e.data_access.dal import DataAccessLayer
from pete_e.infra import log_utils


class JsonDal(DataAccessLayer):
    """
    A Data Access Layer implementation that uses JSON files as the backend.
    This class fulfills the contract defined by the DataAccessLayer ABC,
    providing a concrete implementation for each data operation.
    """

    def _read_json_file(self, path) -> Dict | List:
        """Helper function to read a JSON file safely."""
        if not path.exists():
            log_utils.log_message(f"File not found: {path}", "WARN")
            # Return a list for history, dict for others, to avoid downstream errors
            return [] if 'history' in path.name else {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError) as e:
            log_utils.log_message(f"Error reading {path}: {e}", "ERROR")
            return [] if 'history' in path.name else {}

    def _write_json_file(self, path, data) -> None:
        """Helper function to write data to a JSON file safely."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except IOError as e:
            log_utils.log_message(f"Error writing to {path}: {e}", "ERROR")

    def load_lift_log(self) -> Dict[str, Any]:
        """Loads the entire lift log from knowledge/lift_log.json."""
        return self._read_json_file(settings.LIFT_LOG_PATH)

    def save_lift_log(self, log: Dict[str, Any]) -> None:
        """Saves the entire lift log to knowledge/lift_log.json."""
        self._write_json_file(settings.LIFT_LOG_PATH, log)

    def load_history(self) -> Dict[str, Any]:
        """Loads the consolidated history from knowledge/history.json."""
        return self._read_json_file(settings.HISTORY_PATH)

    def save_history(self, history: Dict[str, Any]) -> None:
        """Saves the consolidated history to knowledge/history.json."""
        self._write_json_file(settings.HISTORY_PATH, history)

    def save_daily_summary(self, summary: Dict[str, Any], day: date) -> None:
        """Saves a daily summary to knowledge/daily/{YYYY-MM-DD}.json."""
        path = settings.DAILY_KNOWLEDGE_PATH / f"{day.isoformat()}.json"
        self._write_json_file(path, summary)

    def load_body_age(self) -> Dict[str, Any]:
        """Loads the body age data from knowledge/body_age.json."""
        return self._read_json_file(settings.BODY_AGE_PATH)

    def get_historical_metrics(self, days: int) -> List[Dict[str, Any]]:
        """
        Retrieves the last N days of historical metrics by loading the full
        history file and returning the last N entries.
        """
        history = self.load_history()
        # The history is a dict, so we get its values (the daily entries)
        return list(history.values())[-days:]

