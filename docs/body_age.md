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
* The procedure mirrors the Python helper in `pete_e/domain/body_age.py`. The helper is not part of the production flow but can be used in notebooks for exploratory analysis.

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
