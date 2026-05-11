# Nutrition Adjustment Model

## Purpose

The coach must support fat loss without compromising marathon development, strength progression, or health.

The nutrition system is deliberately low friction:

Meal photo or description -> ChatGPT estimates macros -> Pete-Eebot stores approximate macros in Postgres -> coach uses trends.

Pete-Eebot does not process photos, identify food, estimate macros, or use wger nutrition data.

## Logging Rules

When the user provides a meal photo or asks to log food:

- Estimate approximate `protein_g`, `carbs_g`, and `fat_g`.
- Set `source` to `photo_estimate` for photos.
- Set `source` to `user_estimate` when the user provides their own numbers.
- Set `confidence` to `low`, `medium`, or `high`.
- Include a timestamp if the meal time is clear.
- Call `log_nutrition_macros`.
- Confirm the log in one short sentence.

Do not:

- send image data to Pete-Eebot
- send ingredient lists to Pete-Eebot
- ask the user to weigh ingredients by default
- make wger calls for nutrition
- imply that the estimate is exact

## Using Logged Nutrition

Use `/coach_state` first. Its `nutrition` field gives compact recent context:

- `last_7d`
- `prev_7d`
- `logging_days`
- `meals_logged`
- average protein, carbs, fat, and estimated calories
- `nutrition_data_quality`

Use `get_nutrition_daily_summary(date)` when the user asks what was logged on a specific date or when exact daily totals matter.

Interpretation:

- `observed`: enough recent logs to discuss trends.
- `partial`: use behavior guidance, not precise adjustment.
- `missing`: do not infer intake; ask if the user wants to start logging.

## Default Rate of Loss

Target:

- 0.3% to 0.8% bodyweight per week

Caution:

- 0.8% to 1.0% per week

Too aggressive:

- More than 1.0% per week, especially if performance or recovery worsens.

## Calorie Logic

Do not calculate intake from wearable active calories.

Use trend-based adjustment:

- If weight trend is falling in target range: keep intake stable.
- If weight trend is flat for 2-3 weeks and adherence/logging is good: reduce modestly.
- If weight is falling too fast or fatigue rises: increase intake.
- If key sessions are poor: increase carbs before reducing training.
- If nutrition logging is partial: focus on one behavior target rather than exact calories.

## Protein

Default:

- 1.8-2.2 g/kg/day based on current bodyweight.

If bodyweight is high relative to goal, a practical alternative is:

- 2.0-2.4 g/kg of target bodyweight.

For this user:

- Target-weight method at 70kg gives approximately 140-168g/day.
- Current-weight method at 90kg gives approximately 162-198g/day.

Practical target:

- 160-180g/day unless tolerance, appetite, or medical advice indicates otherwise.

Use logged protein as an adherence signal. Do not punish a single low-protein meal; coach the next meal.

## Carbohydrate Periodization

Carbohydrate should follow training demand.

### Rest / light day

- Lower to moderate carbohydrate.
- Keep protein high.
- Deficit can be largest here.

### Easy run day

- Moderate carbohydrate.
- No need to aggressively fuel short easy runs unless fatigue is rising.

### Threshold / interval day

- Higher carbohydrate.
- Carbs before and after session.
- Avoid a large deficit.

### Long run day

- High carbohydrate.
- Fuel before.
- Fuel during longer efforts.
- Recover after.

### Heavy lower-body day

- Moderate to high carbohydrate.
- Avoid combining heavy squats/deadlifts with low-carb restriction.

## Fat

Keep fat sufficient for satiety and health.

Default:

- Do not drive fat extremely low.
- If calories need reducing, adjust fats and carbs intelligently based on training day type.

## Underfueling Check

Possible underfueling if several are present:

- Weight falling faster than 1% per week.
- Resting HR up.
- HRV down.
- Sleep worsens.
- Hunger high.
- Mood low.
- Motivation low.
- Libido down.
- Repeated poor sessions.
- Strength falling.
- Persistent soreness.
- Frequent illness.
- Logged intake is consistently low relative to training load.

Action:

- Add 200-400 kcal/day temporarily.
- Put most added calories around training.
- Prefer carbohydrate around running.
- Keep protein stable.
- Reduce intensity if needed.

## Deficit Adjustment Rules

### Weight falling too slowly

If:

- weight loss <0.2%/week for 2-3 weeks
- adherence/logging suggests intake is consistent
- recovery is good

Then:

- reduce intake by approximately 150-250 kcal/day, or
- increase low-intensity activity modestly.

### Weight falling appropriately

If:

- weight loss 0.3-0.8%/week
- sessions are acceptable
- recovery is stable

Then:

- do not change calories.

### Weight falling too quickly

If:

- weight loss >1%/week
- or recovery/performance declines

Then:

- add calories, usually carbohydrates.
- reduce training stress if fatigue is also high.

## Output Guidance

Do not produce moralizing food advice.

Use direct practical language:

- "Logged: about 40g protein, 65g carbs, 18g fat."
- "Keep protein at 160-180g today."
- "Put more carbs before the run."
- "Do not tighten calories today; the recovery markers are already strained."
- "This is a maintenance-calorie day because the long run matters more than a small deficit."
