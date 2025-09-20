# Body Age Calculation Notes

## Current Pipeline

* Daily sync orchestrator calls `PostgresDal.compute_body_age_for_date` for each date in the sync window. That DAL method executes the stored procedure `sp_upsert_body_age`, which persists the composite score in `body_age_daily`.
* `sp_upsert_body_age` reads from the `daily_summary` materialised view. The procedure averages the following fields over a seven day window ending on the target date:
  * `steps`
  * `exercise_minutes`
  * `hr_resting`
  * `sleep_asleep_minutes`
  * Body composition continues to come from Withings (`body_fat_pct`).
* The procedure mirrors the legacy Python helper (`pete_e/domain/body_age.py`). The helper is not part of the production flow but can be used in notebooks for exploratory analysis.

## Upcoming Enhancements

The new Apple Health schema unlocks richer metrics that we can fold into the body age composite:

* **VO₂ max** – Apple Health exposes this as `MetricType.name = 'vo2_max'`. Once the value is surfaced in `daily_summary` (or a sibling view) the stored procedure and Python helper can skip the proxy formula and scale the direct VO₂ max reading. Toggle `used_vo2max_direct` to `true` when doing so.
* **Heart Rate Variability (HRV)** – HRV (SDNN) can help refine the recovery score. A prolonged drop could subtract points from the sleep/resting HR blend.
* Additional Apple-only metrics should be considered if they materially improve the composite. Update `daily_summary` first so the database and Python implementations stay aligned.

## Action Items

1. Surface VO₂ max and HRV in `daily_summary` once the upstream ingestion lands those metrics.
2. Update `sp_upsert_body_age` to consume the new columns and adjust the scoring weights if necessary.
3. Mirror the logic in `pete_e/domain/body_age.py` so ad-hoc analytics match production results.
