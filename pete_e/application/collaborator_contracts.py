"""Interface-style contracts for orchestrator collaborators."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import date
from typing import Any, Dict, Iterable, Protocol, Sequence, Tuple

from pete_e.application.validation_service import ValidationService
from pete_e.domain.cycle_service import CycleService


class DataAccessContract(Protocol):
    def hold_plan_generation_lock(self) -> AbstractContextManager[Any]: ...

    def close(self) -> None: ...

    def get_active_plan(self) -> Dict[str, Any] | None: ...

    def get_metrics_overview(self, target: date) -> Tuple[Sequence[str], Iterable[Sequence[Any]]]: ...

    def get_plan_for_day(self, target: date) -> Tuple[Sequence[str], Iterable[Sequence[Any]]]: ...

    def get_historical_data(self, start_date: date, end_date: date) -> Iterable[Any]: ...

    def get_recent_running_workouts(self, *, days: int, end_date: date) -> Iterable[Any]: ...


class PlanGenerationContract(Protocol):
    def create_next_plan_for_cycle(self, *, start_date: date) -> int: ...

    def create_and_persist_strength_test_week(self, start_date: date) -> int: ...


class ExportContract(Protocol):
    def export_plan_week(
        self,
        *,
        plan_id: int,
        week_number: int,
        start_date: date,
        force_overwrite: bool,
        validation_decision: Any | None = None,
    ) -> None: ...


class SyncContract(Protocol):
    def run_full(self, *, days: int) -> Any: ...

    def run_withings_only(self, *, days: int) -> Any: ...


class MessagingContract(Protocol):
    def send_message(self, message: str) -> bool: ...


class ValidationContract(Protocol):
    def validate_and_adjust_plan(self, reference_date: date) -> Any: ...


class CycleContract(Protocol):
    def check_and_rollover(self, active_plan: Dict[str, Any] | None, reference_date: date) -> bool: ...


__all__ = [
    "CycleContract",
    "CycleService",
    "DataAccessContract",
    "ExportContract",
    "MessagingContract",
    "PlanGenerationContract",
    "SyncContract",
    "ValidationContract",
    "ValidationService",
]
