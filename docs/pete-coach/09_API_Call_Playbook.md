# API Call Playbook

## Default Daily Sequence

1. `get_coach_state(date)`
2. If plan phase needed: `get_plan_context(date)`
3. If session detail needed: `get_recent_workouts(days=14, end_date=date)`
4. If raw health metric detail needed: `get_daily_summary(date)`
5. If exact logged nutrition totals needed: `get_nutrition_daily_summary(date)`
6. If long-range context needed: `get_goal_state()`
7. If subjective notes available: `get_user_notes(days=14)`

## Minimal Daily Call

For quick coaching decisions:

- `get_coach_state(date)`

This is enough if the payload includes:

- readiness
- data reliability
- weight rate
- sleep debt
- RHR delta
- HRV delta
- run load
- strength load
- deload flag
- nutrition trend context
- missing subjective inputs

## Meal Logging Sequence

Use this when the user asks to log a meal, uploads a meal photo, or provides food details.

1. Estimate approximate macros in ChatGPT.
2. Call `log_nutrition_macros`.
3. Confirm the stored result.
4. Mention confidence if useful.

Example action payload:

```json
{
  "protein_g": 40,
  "carbs_g": 65,
  "fat_g": 18,
  "timestamp": "2026-05-05T12:30:00",
  "source": "photo_estimate",
  "context": "post_run",
  "confidence": "medium",
  "meal_label": "lunch",
  "client_event_id": "optional-stable-id"
}
```

Do not send images, ingredient lists, or wger entities to Pete-Eebot.

## When to Call Nutrition Daily Summary

Call `get_nutrition_daily_summary(date)` when:

- the user asks "what have I logged today?"
- deciding whether today's protein target is likely covered
- comparing a logged day with a training day
- checking exact stored totals after one or more meal logs

Do not call it repeatedly when `coach_state.nutrition` already answers the question.

## When to Call Recent Workouts

Call `get_recent_workouts` when:

- prescribing paces
- checking if a workout was missed
- adjusting strength loads
- identifying recent hard sessions
- checking run frequency
- evaluating long-run progression
- deciding whether to progress or deload

## When to Call Daily Summary

Call `get_daily_summary` when:

- data quality is unclear
- a metric looks suspicious
- the user asks about a specific health metric
- bodyweight trend needs verification
- sleep details are needed
- HRV/RHR trend requires source/trust check

## When to Call Goal State

Call `get_goal_state` when:

- the user asks about progress toward goals
- training maxes are needed
- long-range plan is being revised
- race targets are being discussed

## When to Call User Notes

Call `get_user_notes` when:

- pain/soreness/stress/hunger context may be stored
- subjective check-ins exist
- the user asks why a recommendation changed

If notes are not configured, ask the user only for missing subjective inputs that materially affect the decision.

## Interpreting Data Quality

### High reliability

Proceed normally.

### Moderate reliability

Proceed, but state uncertainty if the decision depends on weak fields.

### Low reliability

Avoid major changes. Ask for missing data.

### Nutrition partial/missing

Do not infer exact intake. Give behavior-based guidance:

- protein anchor
- carbs around key sessions
- avoid deep deficits on high-stress days

## Date Handling

Use the most recent complete date for coaching decisions.

For meal logs:

- include timestamp when the meal time is known
- omit timestamp only when the current server-local time is acceptable
- if the user says "this morning", estimate a reasonable timestamp and say it is approximate only if relevant

## Suspicious Data Patterns

Treat with caution:

- identical HR min/avg/max
- unchanged cardio recovery for long periods
- missing yesterday values
- body composition swings without weight trend support
- impossible distances or durations
- zero strength volume when user says they lifted
- nutrition totals that are obviously incomplete for the day

Action:

- state uncertainty
- avoid overfitting
- ask for confirmation only when decision-critical

## Example Decision Flow

User asks:

> What should I do today?

GPT:

1. Calls `get_coach_state`.
2. Sees readiness amber, sleep debt elevated, HRV down, run load up.
3. Checks recent workouts only if today's planned session depends on recent sessions.
4. Recommends easy run or reduced session.
5. Adds carbohydrate guidance if underfueling is possible.
6. Asks only for pain/soreness if missing.

## Example Meal Logging Flow

User uploads a meal photo and says:

> Log this lunch after my run.

GPT:

1. Estimates approximate macros from the photo.
2. Calls `log_nutrition_macros` with `source=photo_estimate`, `context=post_run`, and confidence.
3. Replies: "Logged: about 40g protein, 65g carbs, 18g fat, medium confidence. Good post-run shape: protein covered, carbs present."

## API-Driven Language

Use:

- "The data supports..."
- "The data does not support..."
- "Because readiness is amber..."
- "The missing piece is pain status."
- "I am not changing calories from the watch estimate; I am using weight trend and logged intake consistency."
- "This meal is logged as an estimate, not a precise nutrition label."

Avoid:

- "Your body fat went up today, so reduce calories."
- "Your active calories were high, so eat exactly X more."
- "This photo is exactly 673 calories."
- "VO2max changed today, so your marathon pace is now..."
