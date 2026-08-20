# Readiness Adjustment Persistence

Readiness assessment and plan mutation are separate operations.
`ValidationService.assess_plan(...)` reads health/adherence data and returns a
decision without changing a plan. `ValidationService.apply_adjustment(...)`
persists that decision for one explicit plan week.

## Baseline and effective prescriptions

For strength rows in `training_plan_workouts`:

- `baseline_sets` and `baseline_rir` are the canonical prescription produced by
  plan generation (or a deliberate operator prescription edit).
- `sets` and `rir` are the effective values used by plan reads and wger export.
- automated readiness application never derives from or writes back into the
  baseline columns. It replaces effective values with
  `round(baseline_sets * set_multiplier)` and
  `baseline_rir + rir_increment` (with a one-set floor).
- A zero-set baseline is retained for legacy/comment-only placeholder rows.
  Those rows are not exercise prescriptions, so readiness application leaves
  both their effective sets and RIR unchanged. Negative set baselines are
  rejected.

A neutral decision (`1.0`, `0`) therefore restores the baseline. If an operator
intentionally changes a persisted prescription, update the baseline and
effective columns together; the next readiness application will derive from the
new baseline.

## Durable identity and audit

`plan_readiness_adjustments` records one row for each logical decision identity:

- plan and plan week;
- readiness policy version;
- SHA-256 identity of the health/adherence source snapshot;
- SHA-256 identity of the workout-level baseline prescription.

The row stores the set/RIR adjustment, source summary, full derived decision,
and the resulting baseline/effective values for each affected workout.
`training_plan_weeks.effective_readiness_adjustment_id` identifies which ledger
row currently defines the effective prescription.

Changing source data, the policy version, or the baseline prescription creates
one new auditable decision. Reapplying an existing identity reuses its ledger
row and converges to the same baseline-derived result.

The policy version is `READINESS_ADJUSTMENT_POLICY_VERSION` in
`pete_e/domain/validation.py`. Bump it when adjustment policy changes in a way
that should be distinguished in audit history.

## Transactions and concurrency

PostgreSQL application locks the target `training_plan_weeks` row. Ledger
insert/reuse, effective workout updates, result snapshot, and the effective
pointer all occur in one transaction. Concurrent duplicate calls serialize and
write the same deterministic values. A failure rolls back both the workout
changes and ledger marker.

## Export semantics

- A normal export checks `wger_export_log` before readiness assessment. An
  already-exported week is skipped without plan mutation.
- Force overwrite means reassess/apply idempotently and replace or resend the
  wger routine. It does not apply another delta to the current prescription.
- Dry-run assessment is non-mutating.
- Morning/daily readiness changes remain scoped to the outgoing wger payload;
  they do not become global persisted plan adjustments.

## Migration compatibility

The migration backfills existing baseline columns from the effective values
present at migration time. Historical pre-migration compounding cannot be
reconstructed automatically; operators should review any plan known to have
been repeatedly adjusted before deployment and correct its baseline explicitly
if necessary.
