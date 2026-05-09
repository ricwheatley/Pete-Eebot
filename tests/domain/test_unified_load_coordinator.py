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


def _context(readiness: float = 0.8):
    assembler = ContextAssembler(StubDal(readiness=readiness, sparse=False))
    coordinator = UnifiedLoadCoordinator(context_assembler=assembler, stress_budget_engine=StressBudgetEngine())
    context = coordinator.assemble_context(plan_start_date=date(2026, 5, 4), week_number=2, goal_phase="build")
    return coordinator, context


def test_constraint_long_run_reduces_lower_body_volume() -> None:
    coordinator, context = _context(0.8)
    candidates = [
        {"session_type": "long_run", "day_of_week": 6, "stress": 9.0},
        {"session_type": "strength", "lower_body": True, "volume_sets": 6, "stress": 8.0},
    ]
    feasible = coordinator.apply_constraints(context, candidates)
    lower = next(s for s in feasible if s["session_type"] == "strength")
    assert lower["volume_sets"] == 4
    assert any(t.stage == "constraint_long_run_lower_strength" for t in coordinator.decision_trace)


def test_constraint_heavy_strength_week_downgrades_run_quality() -> None:
    coordinator, context = _context(0.8)
    candidates = [
        {"session_type": "strength", "day_of_week": 2, "intensity_tag": "heavy_top_set", "lift": "bench", "stress": 7.0},
        {"session_type": "run", "day_of_week": 4, "quality": "high", "stress": 7.0},
    ]
    feasible = coordinator.apply_constraints(context, candidates)
    run = next(s for s in feasible if s["session_type"] == "run")
    assert run["quality"] == "moderate"
    assert run["stress"] == 5.0
    assert any(t.stage == "constraint_heavy_strength_run_quality" for t in coordinator.decision_trace)


def test_constraint_bilateral_backoff_reduces_both_modalities() -> None:
    coordinator, context = _context(0.5)
    candidates = [
        {"session_type": "strength", "day_of_week": 2, "stress": 10.0},
        {"session_type": "run", "day_of_week": 4, "quality": "easy", "stress": 8.0},
    ]
    feasible = coordinator.apply_constraints(context, candidates)
    assert next(s for s in feasible if s["session_type"] == "strength")["stress"] == 8.5
    assert next(s for s in feasible if s["session_type"] == "run")["stress"] == 6.8
    assert any(t.stage == "constraint_bilateral_recovery_backoff" for t in coordinator.decision_trace)


def test_constraint_hard_session_spacing_removes_conflict_without_override() -> None:
    coordinator, context = _context(0.8)
    candidates = [
        {"session_type": "strength", "day_of_week": 3, "lift": "squat", "intensity_tag": "heavy_top_set", "stress": 8.0},
        {"session_type": "run", "day_of_week": 4, "quality": "high", "stress": 7.0},
        {"session_type": "run", "day_of_week": 2, "quality": "high", "stress": 7.0, "override_spacing": True},
    ]
    feasible = coordinator.apply_constraints(context, candidates)
    assert len([s for s in feasible if s["session_type"] == "run"]) == 1
    assert feasible[-1].get("override_spacing") is True
    assert any(t.stage == "constraint_hard_session_spacing" for t in coordinator.decision_trace)


def test_combined_constraints_apply_in_deterministic_order() -> None:
    coordinator, context = _context(0.45)
    candidates = [
        {"session_type": "long_run", "day_of_week": 6, "stress": 10.0},
        {"session_type": "strength", "day_of_week": 5, "lower_body": True, "volume_sets": 7, "intensity_tag": "heavy_top_set", "lift": "deadlift", "stress": 10.0},
        {"session_type": "run", "day_of_week": 6, "quality": "high", "stress": 8.0},
    ]
    feasible = coordinator.apply_constraints(context, candidates)
    strength = next(s for s in feasible if s["session_type"] == "strength")
    assert strength["volume_sets"] == 4
    assert strength["stress"] == 8.5
    assert len([s for s in feasible if s["session_type"] == "run"]) == 0
    stages = [t.stage for t in coordinator.decision_trace if t.reason_code.value == "constraint_applied"]
    assert stages.index("constraint_long_run_lower_strength") < stages.index("constraint_heavy_strength_run_quality") < stages.index("constraint_bilateral_recovery_backoff") < stages.index("constraint_hard_session_spacing")
