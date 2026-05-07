from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Iterable, List, Sequence


@dataclass
class PlanReadModel:
    """Read-model responsible for plan snapshot retrieval and row normalization."""

    dal: Any

    def plan_for_day(self, target_date: date) -> Dict[str, Any]:
        columns, rows = self.dal.get_plan_for_day(target_date)
        return {"columns": list(columns or []), "rows": self._normalise_rows(columns, rows)}

    def plan_for_week(self, start_date: date) -> Dict[str, Any]:
        columns, rows = self.dal.get_plan_for_week(start_date)
        return {"columns": list(columns or []), "rows": self._normalise_rows(columns, rows)}

    def load_day_context(self, target_date: date) -> List[Dict[str, Any]]:
        """Load normalized daily plan rows suitable for trainer/context consumers."""

        snapshot = self.plan_for_day(target_date)
        return list(snapshot.get("rows") or [])

    @staticmethod
    def _normalise_rows(
        columns: Sequence[str] | None,
        rows: Iterable[Sequence[Any] | Dict[str, Any]] | None,
    ) -> List[Dict[str, Any]]:
        if not rows:
            return []

        column_index = {name: idx for idx, name in enumerate(columns or [])}
        normalised: List[Dict[str, Any]] = []
        for row in rows:
            if isinstance(row, dict):
                normalised.append(dict(row))
                continue
            if not isinstance(row, Sequence) or isinstance(row, (str, bytes)):
                continue

            record: Dict[str, Any] = {}
            for name, idx in column_index.items():
                try:
                    record[name] = row[idx]
                except (IndexError, TypeError):
                    continue
            if record:
                normalised.append(record)
        return normalised
