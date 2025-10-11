from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Optional

try:  # pragma: no cover - dependency may be stubbed in tests
    from psycopg import Error as PsycopgError  # type: ignore[attr-defined]
except (ImportError, AttributeError):  # pragma: no cover - fallback for stubs
    PsycopgError = RuntimeError  # type: ignore[assignment]

from pete_e.application.exceptions import DataAccessError
from pete_e.domain.data_access import DataAccessLayer
from pete_e.domain.validation import PlanContext, resolve_plan_context


@dataclass
class ApplicationPlanService:
    """Application-level helper that loads plan context for domain logic."""

    dal: DataAccessLayer

    def get_plan_context(self, week_start: date) -> Optional[PlanContext]:
        """Fetch the current plan context, falling back to the requested week."""

        plan: Optional[Dict[str, Any]] = None

        try:
            plan = self.dal.get_active_plan()
        except (PsycopgError, RuntimeError) as exc:
            raise DataAccessError("Failed to load active plan.") from exc

        context = resolve_plan_context(plan)
        if context:
            return context

        try:
            plan = self.dal.find_plan_by_start_date(week_start)
        except (PsycopgError, RuntimeError) as exc:
            raise DataAccessError("Failed to load plan for requested week.") from exc

        if plan is None:
            return None

        return resolve_plan_context(plan, default_start=week_start)

