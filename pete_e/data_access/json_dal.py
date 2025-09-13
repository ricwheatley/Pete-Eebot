"""JSON file-based implementation of the Data Access Layer."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from pete_e.config import settings
from pete_e.infra import log_utils
from .dal import DataAccessLayer


class JsonDal(DataAccessLayer):
    """Data Access Layer that persists data to JSON files on disk."""

    def _read_json(self, path: Path) -> Any:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _write_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)

    # --- Lift Log Operations -------------------------------------------------
    def load_lift_log(self) -> Dict[str, Any]:
        return self._read_json(settings.lift_log_path)

    def save_lift_log(self, log: Dict[str, Any]) -> None:
        self._write_json(settings.lift_log_path, log)

    def save_strength_log_entry(
        self,
        exercise_id: int,
        log_date: date,
        reps: int,
        weight_kg: float,
        rir: Optional[float] = None,
    ) -> None:
        log = self.load_lift_log()
        key = str(exercise_id)
        log.setdefault(key, [])
        log[key].append(
            {
                "date": log_date.isoformat(),
                "reps": reps,
                "weight": weight_kg,
                "rir": rir,
            }
        )
        self.save_lift_log(log)

    # --- History Operations --------------------------------------------------
    def load_history(self) -> Dict[str, Any]:
        return self._read_json(settings.history_path)

    def save_history(self, history: Dict[str, Any]) -> None:
        self._write_json(settings.history_path, history)

    def save_daily_summary(self, summary: Dict[str, Any], day: date) -> None:
        daily_path = settings.daily_knowledge_path / f"{day.isoformat()}.json"
        self._write_json(daily_path, summary)
        history = self.load_history()
        history[day.isoformat()] = summary
        self.save_history(history)

    # --- Analytical Helpers --------------------------------------------------
    def load_body_age(self) -> Dict[str, Any]:
        return self._read_json(settings.body_age_path)

    def get_historical_metrics(self, days: int) -> List[Dict[str, Any]]:
        history = self.load_history()
        sorted_days = sorted(history.keys())[-days:]
        return [history[d] for d in sorted_days]

    def get_daily_summary(self, target_date: date) -> Optional[Dict[str, Any]]:
        daily_path = settings.daily_knowledge_path / f"{target_date.isoformat()}.json"
        if not daily_path.exists():
            return None
        return self._read_json(daily_path)

    def get_historical_data(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        current = start_date
        while current <= end_date:
            summary = self.get_daily_summary(current)
            if summary is not None:
                out.append(summary)
            current += timedelta(days=1)
        return out

    # --- Plan & Validation Persistence --------------------------------------
    def save_training_plan(self, plan: dict, start_date: date) -> None:
        """Write the training plan to disk under wger_plans_path."""
        path = settings.wger_plans_path / f"plan_{start_date.isoformat()}.json"
        self._write_json(path, plan)

    def save_validation_log(self, tag: str, adjustments: List[str]) -> None:
        """Persist validation logs via the central log util."""
        log_utils.log_message(f"{tag}: {adjustments}", "INFO")
