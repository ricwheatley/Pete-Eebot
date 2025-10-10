from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, Iterable, List

from pete_e.config import settings
from pete_e.domain.data_access import DataAccessLayer
from pete_e.domain.progression import PlanProgressionDecision, calibrate_plan_week
from pete_e.infrastructure import log_utils


def _extract_exercise_ids(rows: Iterable[Dict[str, Any]]) -> List[int]:
    ids: List[int] = []
    seen: set[int] = set()
    for row in rows:
        ex_id = row.get("exercise_id")
        if ex_id is None:
            continue
        try:
            value = int(ex_id)
        except (TypeError, ValueError):
            continue
        if value not in seen:
            seen.add(value)
            ids.append(value)
    return ids


class ProgressionService:
    """Application service that prepares data for progression logic."""

    def __init__(self, dal: DataAccessLayer) -> None:
        self._dal = dal

    def calibrate_plan_week(
        self,
        plan_id: int,
        week_number: int,
        *,
        persist: bool = True,
    ) -> PlanProgressionDecision:
        rows = self._dal.get_plan_week(plan_id, week_number)
        if not rows:
            return PlanProgressionDecision(notes=[], updates=[], persisted=False)

        exercise_ids = _extract_exercise_ids(rows)
        lift_history = {}
        if exercise_ids:
            lift_history = self._dal.load_lift_log(exercise_ids=exercise_ids)

        recent_metrics = self._dal.get_historical_metrics(7)
        baseline_metrics = self._dal.get_historical_metrics(settings.BASELINE_DAYS)

        decision = calibrate_plan_week(
            rows,
            lift_history=lift_history,
            recent_metrics=recent_metrics,
            baseline_metrics=baseline_metrics,
        )

        if not persist or not decision.updates:
            return decision

        payload = [
            {"workout_id": item.workout_id, "target_weight_kg": item.after}
            for item in decision.updates
        ]

        persisted = False
        try:
            self._dal.update_workout_targets(payload)
        except Exception as exc:  # pragma: no cover - defensive guardrail
            log_utils.log_message(
                f"Failed to update workout targets: {exc}",
                "ERROR",
            )
        else:
            persisted = True
            try:
                self._dal.refresh_plan_view()
            except Exception as exc:  # pragma: no cover - defensive guardrail
                log_utils.log_message(
                    f"Failed to refresh plan view after progression updates: {exc}",
                    "WARN",
                )

        if persisted:
            return replace(decision, persisted=True)
        return decision
