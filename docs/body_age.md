# Body Age Calculation Notes

## Current Pipeline

* Daily sync refreshes `daily_summary`, calls `sp_upsert_body_age_range`, then refreshes `daily_summary` again so the body-age output uses newly synced source metrics and is surfaced in the summary table.
* `sp_upsert_body_age` reads from `daily_summary`. The procedure averages the following fields over a seven-day window ending on the target date:
  * `steps`
  * `exercise_minutes`
  * `hr_resting`
  * `sleep_asleep_minutes`
  * `vo2_max`
  * `hrv_sdnn_ms`
  * Withings body composition: `body_fat_pct`, plus `visceral_fat_index` and `muscle_pct` when a usable Body Comp window is available.
* The procedure is the production calculation source of truth. The separate
  `calculate_body_age` helper in `pete_e/domain/body_age.py` is exploratory and
  is not guaranteed to have identical time-window or fallback semantics.

## Seven-Day History Trend

The read-side Body Age trend does not calculate Body Age. It compares body-age
values already present in history rows:

* `get_body_age_trend(dal, target_date=None)` remains the compatibility facade
  used by the CLI messenger and application orchestrator.
* `BodyAgeHistoryReader` owns the narrow, infrastructure-free row contract.
  The legacy adapter prefers `get_historical_data(start, target)` and uses
  `get_historical_metrics(8)` only when the range capability is absent or not
  callable.
* `analyze_body_age_trend(rows, target_date)` is the pure normalization and
  decision boundary. It selects the latest valid sample in the inclusive
  `target_date - 7 days` through `target_date` window, and calculates a delta
  only when a sample exists on the exact seven-day comparison date.

These trend semantics are intentionally independent of the SQL procedure's
seven-day scoring window. Changing the trend does not change
`sp_upsert_body_age`, and changing the calculator does not redefine the trend.

## Enriched Withings Body Comp

The enriched body-composition path starts from the first complete seven-day window after the Body Comp scale started recording richer fields:

* Scale start date: `2026-04-06`
* First enriched target date: `2026-04-12`
* Minimum enriched rows in the seven-day window: `3`
* Earlier dates, sparse windows, or missing enriched fields fall back to the original body-fat-only score.

The enriched body-composition subscore keeps the existing body-fat score as the anchor, then blends:

* `60%` body fat percent score
* `25%` visceral fat index score
* `15%` muscle percent score

Withings metabolic age and BMR are stored for comparison, but are not direct inputs because they are derived metrics and would double-count the same scale data.
