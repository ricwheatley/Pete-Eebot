from __future__ import annotations

from datetime import date

from pete_e.domain.unified_load_coordinator import (
    ContextAssembler,
    StressBudgetEngine,
    UnifiedLoadCoordinator,
)


class StubDal:
    def __init__(self, readiness: float, sparse: bool = False) -> None:
        self._readiness = readiness
        self._sparse = sparse

    def get_latest_training_maxes(self):
        return {} if self._sparse else {"squat": 140.0, "bench": 100.0}

    def get_recent_running_workouts(self, *, days: int, end_date: date):
        if self._sparse:
            return []
        return [
            {"duration_sec": 2400, "total_distance_km": 5.0},
            {"duration_sec": 3600, "total_distance_km": 8.0},
        ]

    def get_historical_metrics(self, days: int):
        if self._sparse:
            return []
        score = self._readiness * 100.0
        return [{"hrv_recovery_score": score, "body_battery": score} for _ in range(14)]

    def get_recent_strength_workouts(self, *, days: int, end_date: date):
        if self._sparse:
            return []
        return [
            {"volume_kg": 5000.0},
            {"volume_kg": 4500.0},
        ]

    def get_recent_adherence_signal(self, *, days: int, end_date: date):
        return 0.9


def _compute_budget(readiness: float, sparse: bool = False):
    assembler = ContextAssembler(StubDal(readiness=readiness, sparse=sparse))
    coordinator = UnifiedLoadCoordinator(context_assembler=assembler, stress_budget_engine=StressBudgetEngine())
    context = coordinator.assemble_context(plan_start_date=date(2026, 5, 4), week_number=1, goal_phase="build")
    budget = coordinator.compute_budget(context)
    return context, budget


def test_green_readiness_budget() -> None:
    _, budget = _compute_budget(0.8)
    assert budget.target > 70
    assert budget.run_target > budget.strength_target
    assert budget.confidence >= 0.8


def test_amber_readiness_budget() -> None:
    _, budget = _compute_budget(0.55)
    assert budget.target > 60
    assert budget.minimum < budget.target < budget.maximum


def test_red_readiness_budget() -> None:
    _, budget = _compute_budget(0.25)
    assert budget.target < 80
    assert budget.run_target <= budget.target * 0.51


def test_sparse_data_mode_sets_flags_and_lower_confidence() -> None:
    context, budget = _compute_budget(0.5, sparse=True)
    assert context.insufficient_data_flags
    assert "missing_training_maxes" in context.insufficient_data_flags
    assert budget.insufficient_data_flags == context.insufficient_data_flags
    assert budget.confidence < 0.8
