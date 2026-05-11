# Trend Scoring Model

## Purpose

This model converts Pete-Eebot API trends into coaching interpretation.

The GPT should not expose every score unless useful. The model exists to make decisions consistent.

## Core Inputs

From `get_coach_state(date)`:

- `summary.readiness_state`
- `summary.data_reliability_flag`
- `summary.possible_underfueling_flag`
- `summary.deload_due`
- `derived.weight_rate_pct_bw_per_week`
- `derived.sleep_debt_7d_minutes`
- `derived.rhr_delta_vs_28d_bpm`
- `derived.hrv_delta_vs_28d_ms`
- `derived.run_load_7d_km`
- `derived.strength_load_7d_kg`
- `nutrition.last_7d`
- `nutrition.prev_7d`
- `nutrition.data_quality.nutrition_data_quality`

From `get_daily_summary(date)`:

- weight
- resting heart rate
- HRV SDNN
- sleep total / asleep minutes
- exercise minutes
- distance
- steps
- VO2 max trend
- body composition fields, low confidence only

From `get_nutrition_daily_summary(date)`:

- logged protein, carbs, fat, and estimated calories for the requested date
- meal count
- source and confidence breakdown

From `get_recent_workouts(days, end_date)`:

- run frequency
- run distance
- session type
- pace
- average heart rate
- maximum heart rate
- elevation gain
- strength top set
- volume
- RIR

## Trend Windows

### 7-day window

Use for acute state:

- recent fatigue
- current load
- current weight movement
- sleep debt
- nutrition logging consistency
- short-term adherence

### 28-day window

Use for baseline:

- current training norm
- meaningful body-mass trend
- normal HRV/RHR range
- recent consistency

### 90-day window

Use for strategic direction:

- base fitness development
- VO2max direction
- long-term sleep pattern
- long-term weight trend
- long-term activity consistency

## Scoring Categories

Use five internal categories:

| Category | Meaning |
|---|---|
| +2 | Strongly favorable |
| +1 | Mildly favorable |
| 0 | Neutral or unclear |
| -1 | Mild concern |
| -2 | Strong concern |

## Weight Trend Score

Use `weight_rate_pct_bw_per_week`.

| Rate | Score | Interpretation |
|---:|---:|---|
| -0.3% to -0.8% | +2 | Ideal performance-compatible loss |
| -0.1% to -0.3% | +1 | Slow but acceptable |
| 0% to +0.3% | 0 | Maintenance / possible stall |
| -0.8% to -1.0% | -1 | Watch fueling and recovery |
| < -1.0% | -2 | Too aggressive for concurrent goals |
| > +0.3% | -1 | Moving away from fat-loss target unless planned |

Do not adjust calories from one weigh-in. Use rolling trend.

## Nutrition Logging Score

Use `nutrition.data_quality.nutrition_data_quality` and `nutrition.last_7d.logging_days`.

| Pattern | Score | Interpretation |
|---|---:|---|
| 5-7 logged days in last 7 | +1 | Trend is usable |
| 2-4 logged days in last 7 | 0 | Partial context only |
| 0-1 logged days in last 7 | 0 | Do not infer intake |
| Low logged calories plus poor recovery | -1 | Underfueling possible |
| Low logged calories plus rapid weight loss and performance decline | -2 | Strong underfueling concern |

Do not treat photo-estimated macros as exact. Use them to guide behavior and trends.

## Sleep Score

Use `sleep_debt_7d_minutes`.

Interpret sleep debt relative to at least 7 hours per night unless the API provides a personal target.

| 7-day sleep debt | Score | Action |
|---:|---:|---|
| 0 to 120 min | +1 | Normal training allowed |
| 120 to 240 min | 0 | Monitor |
| 240 to 420 min | -1 | Avoid hard run plus heavy lift stacking |
| >420 min | -2 | Reduce intensity or volume |

If the user reports feeling unusually tired, downgrade by one level.

## Resting Heart Rate Score

Use `rhr_delta_vs_28d_bpm`.

| RHR delta | Score | Interpretation |
|---:|---:|---|
| <= -2 bpm | +1 | Favorable or recovered |
| -2 to +3 bpm | 0 | Normal |
| +3 to +6 bpm | -1 | Fatigue, stress, heat, illness, or underfueling possible |
| > +6 bpm | -2 | Strong recovery warning |

Do not act on RHR alone. Combine with HRV, sleep, symptoms, load, and nutrition context.

## HRV Score

Use `hrv_delta_vs_28d_ms`.

Because HRV varies by person, use direction and magnitude conservatively.

| HRV pattern | Score | Interpretation |
|---|---:|---|
| Above baseline and stable | +1 | Favorable |
| Slightly below baseline | 0 | Normal variation |
| Meaningfully below baseline | -1 | Possible fatigue |
| Meaningfully below baseline plus RHR up | -2 | Strong fatigue warning |

## Load Score

Use recent workload relative to baseline.

If only 7-day load is available, compare against plan context and recent rolling averages where exposed.

| Pattern | Score |
|---|---:|
| Load rising gradually and recovery stable | +1 |
| Load stable and recovery stable | 0 |
| Load sharply rising but recovery stable | -1 |
| Load sharply rising and recovery worsening | -2 |
| Load absent due to missed training | depends on context |

## Composite Interpretation

Do not mechanically add scores and report a number.

### Positive day

- Weight trend acceptable
- Sleep acceptable
- RHR stable
- HRV stable
- No injury/pain
- Load not spiking
- Nutrition logging does not suggest underfueling

Action: progress planned session.

### Caution day

- One or two mild negatives
- No major injury or illness flags
- Nutrition data partial or recovery slightly strained

Action: maintain plan, reduce optional extras.

### Recovery day

- Two or more strong negatives
- Or readiness red
- Or pain/illness flag
- Or underfueling pattern is plausible

Action: reduce intensity, reduce volume, or rest.

## Rule Against False Precision

Do not say "your score is 6/10" unless the API explicitly returns a score.

Use qualitative outputs:

- Green and progressing
- Amber but trainable
- Amber and reduce extras
- Red and recover
