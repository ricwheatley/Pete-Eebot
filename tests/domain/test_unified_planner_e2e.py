from __future__ import annotations

from datetime import date

from pete_e.domain.unified_load_coordinator import SessionConstraintSet, GlobalTrainingContext, UnifiedLoadCoordinator, WeeklyStressBudget


def _resolve_week(*, readiness: float, run_stress: float, long_run: bool) -> list[dict]:
    coordinator = UnifiedLoadCoordinator()
    context = GlobalTrainingContext(
        plan_start_date=date(2026, 5, 4),
        week_number=2,
        readiness_score=readiness,
        historical_weekly_load=90.0,
        constraints=SessionConstraintSet(max_sessions=6, min_recovery_days=1),
    )
    budget = WeeklyStressBudget(target=90.0, minimum=75.0, maximum=95.0, run_target=50.0, strength_target=40.0, confidence=0.8)
    strength = [
        {"source": "strength", "session_type": "strength", "day_of_week": 2, "lift": "squat", "intensity_tag": "heavy_top_set", "volume_sets": 6, "stress": 11.0},
        {"source": "strength", "session_type": "strength", "day_of_week": 5, "lift": "deadlift", "intensity_tag": "moderate", "volume_sets": 5, "stress": 8.0},
    ]
    runs = [
        {"source": "run", "session_type": "run", "day_of_week": 3, "quality": "high", "stress": run_stress},
        {"source": "run", "session_type": "run", "day_of_week": 4, "quality": "easy", "stress": 4.0, "optional": True},
    ]
    if long_run:
        runs.append({"source": "run", "session_type": "long_run", "day_of_week": 6, "quality": "moderate", "stress": 10.0})

    candidates = coordinator.generate_candidates(context, budget, strength_candidates=strength, run_candidates=runs)
    feasible = coordinator.apply_constraints(context, candidates)
    return coordinator.finalize_week(context, feasible, budget)


def test_fixture_high_readiness_build_week_snapshot_like() -> None:
    finalized = _resolve_week(readiness=0.82, run_stress=7.0, long_run=True)
    assert len(finalized) >= 3
    assert any(s["session_type"] == "long_run" for s in finalized)


def test_fixture_low_readiness_backoff_week_snapshot_like() -> None:
    finalized = _resolve_week(readiness=0.32, run_stress=7.0, long_run=True)
    high_quality = [s for s in finalized if s.get("quality") == "high"]
    assert not high_quality
    assert all(float(s.get("stress", 0.0)) <= 10.0 for s in finalized)


def test_fixture_mixed_load_long_run_pressure_snapshot_like() -> None:
    finalized = _resolve_week(readiness=0.55, run_stress=8.0, long_run=True)
    assert any(s["session_type"] == "strength" for s in finalized)
    assert sum(float(s.get("stress", 0.0)) for s in finalized) <= 95.0
