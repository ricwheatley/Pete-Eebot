from datetime import date, timedelta
from typing import Any, Dict, Optional

import pytest

import tests.config_stub  # noqa: F401

from pete_e.application.exceptions import DataAccessError
from pete_e.application.plan_context_service import ApplicationPlanService
from pete_e.domain.validation import PlanContext


class StubDal:
    def __init__(
        self,
        *,
        active_plan: Optional[Dict[str, Any]] = None,
        fallback_plan: Optional[Dict[str, Any]] = None,
        active_raises: bool = False,
        fallback_raises: bool = False,
    ) -> None:
        self._active_plan = active_plan
        self._fallback_plan = fallback_plan
        self._active_raises = active_raises
        self._fallback_raises = fallback_raises
        self.requested_start: Optional[date] = None

    def get_active_plan(self) -> Optional[Dict[str, Any]]:
        if self._active_raises:
            raise RuntimeError("boom")
        return self._active_plan

    def find_plan_by_start_date(self, start_date: date) -> Optional[Dict[str, Any]]:
        self.requested_start = start_date
        if self._fallback_raises:
            raise RuntimeError("boom")
        return self._fallback_plan


def test_returns_context_from_active_plan() -> None:
    start = date(2024, 6, 3)
    dal = StubDal(active_plan={"id": 12, "start_date": start})
    service = ApplicationPlanService(dal)

    context = service.get_plan_context(start + timedelta(days=1))

    assert context == PlanContext(plan_id=12, start_date=start)


def test_falls_back_to_lookup_by_week_start() -> None:
    week_start = date(2024, 7, 8)
    dal = StubDal(active_plan=None, fallback_plan={"id": 33, "start_date": None})
    service = ApplicationPlanService(dal)

    context = service.get_plan_context(week_start)

    assert context == PlanContext(plan_id=33, start_date=week_start)
    assert dal.requested_start == week_start


def test_returns_none_when_no_plan_available() -> None:
    dal = StubDal(active_plan=None, fallback_plan=None, fallback_raises=False)
    service = ApplicationPlanService(dal)

    context = service.get_plan_context(date(2024, 8, 5))

    assert context is None


def test_raises_data_access_error_when_dal_fails() -> None:
    dal = StubDal(active_plan=None, fallback_plan=None, fallback_raises=True)
    service = ApplicationPlanService(dal)

    with pytest.raises(DataAccessError):
        service.get_plan_context(date(2024, 8, 5))
