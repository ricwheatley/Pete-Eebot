from __future__ import annotations

from datetime import date

from pete_e.domain.unified_load_coordinator import (
    GlobalTrainingContext,
    PlanDecisionReasonCode,
    PlanDecisionTrace,
    SessionConstraintSet,
    UnifiedLoadCoordinator,
    WeeklyStressBudget,
)


def test_domain_models_store_expected_values() -> None:
    constraints = SessionConstraintSet(max_sessions=4, min_recovery_days=2, disallowed_days=(0,))
    context = GlobalTrainingContext(
        plan_start_date=date(2026, 5, 4),
        week_number=2,
        readiness_score=0.7,
        historical_weekly_load=92.5,
        constraints=constraints,
    )
    budget = WeeklyStressBudget(target=110.0, minimum=90.0, maximum=130.0)

    assert context.constraints.max_sessions == 4
    assert context.readiness_score == 0.7
    assert budget.maximum == 130.0


def test_plan_decision_trace_serialization_contract() -> None:
    trace = PlanDecisionTrace(
        week_number=1,
        stage="compute_budget",
        reason_code=PlanDecisionReasonCode.BUDGET_COMPUTED,
        detail="Budget generated.",
        payload={"target": 100.0},
    )

    assert trace.to_dict() == {
        "week_number": 1,
        "stage": "compute_budget",
        "reason_code": "budget_computed",
        "detail": "Budget generated.",
        "payload": {"target": 100.0},
    }


def test_coordinator_emits_trace_across_phase0_pipeline(caplog) -> None:
    caplog.set_level("INFO", logger="pete_e.domain")
    coordinator = UnifiedLoadCoordinator()

    context = coordinator.assemble_context(plan_start_date=date(2026, 5, 4), week_number=1)
    budget = coordinator.compute_budget(context)
    candidates = coordinator.generate_candidates(context, budget)
    feasible = coordinator.apply_constraints(context, candidates)
    finalized = coordinator.finalize_week(context, feasible)

    assert finalized == []
    assert [trace.reason_code for trace in coordinator.decision_trace] == [
        PlanDecisionReasonCode.CONTEXT_ASSEMBLED,
        PlanDecisionReasonCode.BUDGET_COMPUTED,
        PlanDecisionReasonCode.CANDIDATE_GENERATED,
        PlanDecisionReasonCode.CONSTRAINT_APPLIED,
        PlanDecisionReasonCode.WEEK_FINALIZED,
    ]
    assert "plan_decision_trace=" in caplog.text
