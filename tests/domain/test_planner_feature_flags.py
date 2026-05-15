from __future__ import annotations

from datetime import date

import pytest

from pete_e.domain.planner_flags import PlannerFeatureFlags, parse_planner_feature_flags
from pete_e.domain.unified_load_coordinator import (
    GlobalTrainingContext,
    PlanDecisionReasonCode,
    SessionConstraintSet,
    UnifiedLoadCoordinator,
    WeeklyStressBudget,
)


def _spacing_fixture(feature_flags: PlannerFeatureFlags | None = None) -> tuple[list[dict], UnifiedLoadCoordinator]:
    coordinator = UnifiedLoadCoordinator(feature_flags=feature_flags)
    context = GlobalTrainingContext(
        plan_start_date=date(2026, 5, 4),
        week_number=1,
        readiness_score=0.82,
        historical_weekly_load=90.0,
        constraints=SessionConstraintSet(max_sessions=6, min_recovery_days=1),
    )
    budget = WeeklyStressBudget(
        target=90.0,
        minimum=75.0,
        maximum=95.0,
        run_target=50.0,
        strength_target=40.0,
        confidence=0.8,
    )
    strength = [
        {
            "source": "strength",
            "session_type": "strength",
            "day_of_week": 2,
            "lift": "squat",
            "intensity_tag": "heavy_top_set",
            "volume_sets": 5,
            "stress": 10.0,
        },
    ]
    runs = [
        {
            "source": "run",
            "session_type": "run",
            "day_of_week": 3,
            "quality": "high",
            "stress": 7.0,
        },
    ]

    candidates = coordinator.generate_candidates(context, budget, strength_candidates=strength, run_candidates=runs)
    feasible = coordinator.apply_constraints(context, candidates)
    finalized = coordinator.finalize_week(context, feasible, budget)
    return finalized, coordinator


def test_planner_feature_flags_default_to_safe_values() -> None:
    flags = parse_planner_feature_flags("")

    assert flags == PlannerFeatureFlags()
    assert flags.to_dict() == {"experimental_relaxed_session_spacing": False}
    assert flags.non_default_flags() == {}


def test_planner_feature_flags_parse_explicit_overrides() -> None:
    flags = parse_planner_feature_flags("experimental_relaxed_session_spacing=true")

    assert flags.experimental_relaxed_session_spacing is True
    assert flags.non_default_flags() == {"experimental_relaxed_session_spacing": True}


def test_planner_feature_flags_reject_unknown_names() -> None:
    with pytest.raises(ValueError, match="Unknown planner feature flag"):
        parse_planner_feature_flags("unknown_planner_experiment=true")


def test_default_spacing_constraint_drops_nearby_quality_run() -> None:
    finalized, coordinator = _spacing_fixture()

    assert not any(item.get("source") == "run" for item in finalized)
    assert not any(
        item.reason_code == PlanDecisionReasonCode.FEATURE_FLAG_APPLIED
        for item in coordinator.decision_trace
    )


def test_relaxed_spacing_flag_keeps_nearby_quality_run_and_traces_effect() -> None:
    finalized, coordinator = _spacing_fixture(
        PlannerFeatureFlags(experimental_relaxed_session_spacing=True)
    )

    assert any(item.get("source") == "run" for item in finalized)
    effects = [
        item
        for item in coordinator.decision_trace
        if item.reason_code == PlanDecisionReasonCode.FEATURE_FLAG_APPLIED
    ]
    assert len(effects) == 1
    assert effects[0].payload == {
        "flag": "experimental_relaxed_session_spacing",
        "affected_sessions": 1,
    }
