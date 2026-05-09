# Unified Globally Aware Planner: Technical Reference

This document describes the unified globally aware weekly planner used by Pete Eebot. It focuses on the domain coordinator implemented in `pete_e/domain/unified_load_coordinator.py` and its integration path in `pete_e/domain/plan_factory.py`.

## 1) Architecture overview and module map

### End-to-end flow

1. `PlanFactory.create_unified_531_block_plan(...)` builds strength and running candidate workouts for each week.  
2. `UnifiedLoadCoordinator.assemble_context(...)` creates a `GlobalTrainingContext`.  
3. `UnifiedLoadCoordinator.compute_budget(...)` computes a `WeeklyStressBudget`.  
4. `UnifiedLoadCoordinator.generate_candidates(...)` merges run + strength candidates.  
5. `UnifiedLoadCoordinator.apply_constraints(...)` applies deterministic constraints in fixed order.  
6. `UnifiedLoadCoordinator.finalize_week(...)` trims by session cap and stress cap.  
7. Decision trace entries are serialized into `plan.metadata.plan_decision_trace[week]`.

### Module map

- `pete_e/domain/plan_factory.py`
  - orchestration point for weekly plan generation
  - creates modality-specific candidate objects from workouts
  - stores planner metadata (`planner_version`, `plan_decision_trace`)
- `pete_e/domain/unified_load_coordinator.py`
  - planner domain model + control logic
  - `ContextAssembler`: gathers input signals from DAL
  - `StressBudgetEngine`: maps context → stress budget
  - `UnifiedLoadCoordinator`: constraints + finalization + decision trace
- `pete_e/domain/running_planner.py`
  - emits run sessions consumed as run candidates
- `pete_e/application/services.py`
  - maps trace stages to user-readable guidance in messaging pathways
- `pete_e/application/api_services.py`
  - exposes decision trace retrieval for week-level diagnostics

## 2) Data inputs and required DAL methods

`ContextAssembler` expects a DAL-like object with these optional methods (missing methods degrade gracefully to defaults):

- `get_latest_training_maxes() -> dict`
- `get_recent_running_workouts(days: int, end_date: date) -> list[dict]`
- `get_historical_metrics(days: int) -> list[dict]`
- `get_recent_strength_workouts(days: int, end_date: date) -> list[dict]`
- `get_recent_adherence_signal(days: int, end_date: date) -> float | None`

### Expected signal usage

- **Readiness**: derived from latest health metric fields (`hrv_recovery_score`/`hrv_score`, `body_battery`/`recovery_score`), normalized to `[0,1]`.
- **Historical weekly load**: blended estimate from recent run duration and strength volume.
- **Strength workload**: sum of `volume_kg` over recent strength workouts.
- **Insufficient-data flags**:
  - `missing_training_maxes`
  - `limited_running_history` (<2 workouts)
  - `limited_health_history` (<7 metric records)
  - `limited_strength_history` (<2 workouts)

These flags reduce budget confidence and should be surfaced in operator debug output.

## 3) Stress budget algorithm and tuning knobs

`StressBudgetEngine.compute(context)`:

1. **Baseline load**: `base = max(40.0, context.historical_weekly_load or 80.0)`
2. **Readiness multiplier**:
   - readiness `>= 0.7` → `1.10`
   - readiness `>= 0.4` and `< 0.7` → `0.95`
   - readiness `< 0.4` → `0.75`
3. **Phase split (run share of total)**:
   - `build`: `0.55`
   - `peak`: `0.65`
   - `deload`: `0.45`
   - low-readiness clamp: if readiness `<0.4`, split max is `0.50`
4. **Bounds**:
   - `minimum = target * 0.85`
   - `maximum = target * 1.15`
5. **Confidence**:
   - `confidence = clamp(0.95 - 0.15 * flag_count, min=0.2, max=1.0)`

### Tuning knobs

- baseline floor (`40.0`) and fallback (`80.0`)
- readiness bucket cutoffs (`0.7`, `0.4`)
- readiness multipliers (`1.10`, `0.95`, `0.75`)
- phase split table (`build/peak/deload`)
- budget bounds (`±15%`)
- confidence decay per missing-data flag (`0.15`)

## 4) Constraint catalog and reason codes

### Reason codes (`PlanDecisionReasonCode`)

- `context_assembled`
- `budget_computed`
- `candidate_generated`
- `candidate_rejected` (reserved, currently not emitted)
- `constraint_applied`
- `week_finalized`

### Deterministic constraint order

`apply_constraints(...)` executes in this fixed sequence:

1. `constraint_long_run_lower_strength`
   - if long run stress is high and lower-body strength volume exceeds threshold, reduce lower volume sets.
2. `constraint_heavy_strength_run_quality`
   - if heavy top-set strength exists, downgrade high-quality runs to moderate and reduce run stress.
3. `constraint_bilateral_recovery_backoff`
   - when readiness is amber/red, scale down both run and strength stress.
4. `constraint_hard_session_spacing`
   - remove moderate/high-stress run sessions too close to heavy squat/deadlift days unless explicitly overridden.

### Finalization constraints

`finalize_week(...)` then enforces:

- max sessions (`context.constraints.max_sessions`)
- optional-session dropping when cumulative stress would exceed budget maximum

## 5) Decision trace schema + examples

`PlanDecisionTrace` payload schema:

```json
{
  "week_number": 2,
  "stage": "compute_budget",
  "reason_code": "budget_computed",
  "detail": "Computed placeholder weekly stress budget.",
  "payload": {
    "target": 82.5,
    "minimum": 70.1,
    "maximum": 94.9,
    "run_target": 45.4,
    "strength_target": 37.1,
    "confidence": 0.8,
    "insufficient_data_flags": ["limited_running_history"]
  }
}
```

### Example sequence for one week

1. `assemble_context/context_assembled`
2. `compute_budget/budget_computed`
3. `generate_candidates/candidate_generated`
4. zero or more `constraint_* / constraint_applied`
5. `apply_constraints/constraint_applied` summary
6. `finalize_week/week_finalized`

Operators can read this via API/debug surfaces to identify exactly which constraints altered a week.

## 6) How to test and debug bad weekly outcomes

### Fast validation loop

1. Generate the plan for a controlled start date.
2. Inspect `metadata.plan_decision_trace` for the affected week.
3. Check whether budget max or spacing constraint removed key sessions.
4. Verify readiness and data-quality flags.

### Suggested test cases

- **High readiness build week**: expect higher target stress and minimal backoff.
- **Low readiness week**: expect bilateral stress reduction and possible quality-run downgrades.
- **Long-run-heavy week**: expect lower-body volume set capping.
- **Dense heavy-lift week**: expect hard-session spacing removals for nearby quality runs.
- **Sparse data week**: expect low confidence and non-empty insufficient-data flags.

### Practical debug commands

```bash
# Run tests around weekly calibration / planning behavior
pytest tests/test_weekly_calibration.py tests/test_plan_service.py tests/test_weekly_plan_message.py

# Build a plan manually
python -m scripts.generate_plan --start-date 2026-04-06

# Run weekly review automation path
python -m scripts.run_sunday_review
```

### Common failure signatures

- Missing run quality sessions: often `constraint_hard_session_spacing` or heavy-strength quality downgrade.
- Unexpectedly low weekly load: low readiness multiplier and/or bilateral recovery backoff.
- Too many dropped sessions: optional sessions trimmed against budget maximum.
- Unstable week-to-week output: random assistance/core choices (expected unless randomness is seeded).

## Migration note: old split planning docs

If any older documentation still refers to independent run/strength split planning, treat that as historical context only. Current behavior is unified candidate generation followed by globally aware constraints and budget-driven finalization.
