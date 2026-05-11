# Pete-Eebot Coach - Decision Engine

This package defines how the private Custom GPT should use the Pete-Eebot API for coaching and low-friction nutrition logging.

Pete-Eebot is not an image analysis system. The Custom GPT interprets meal photos or user descriptions, estimates approximate macros, and sends only structured macro data to Pete-Eebot. Pete-Eebot persists those estimates in Postgres and exposes them back as coaching context.

## Custom GPT Setup

1. Paste `01_Custom_GPT_Decision_Engine_Instructions.md` into the GPT Instructions field.
2. Upload the remaining Markdown files as Knowledge.
3. Configure the OpenAPI action from `docs/pete_coach_openapi.yaml`.
4. Use `X-API-Key` authentication exactly as defined in the OpenAPI schema.

## Core API Behaviors

The GPT must:

- Call `get_coach_state(date)` before giving training or nutrition advice.
- Use `log_nutrition_macros` when the user asks to log a meal, uploads a meal photo, or provides food/macros to record.
- Use `get_nutrition_daily_summary(date)` when it needs exact logged macro totals for a date.
- Treat logged nutrition as approximate behavior/trend data, not exact calorie accounting.
- Avoid raw wger nutrition entities entirely.
- Avoid sending photos, descriptions, or ingredient guesses to Pete-Eebot; only send structured macros.

## Files

- `01_Custom_GPT_Decision_Engine_Instructions.md` - primary GPT instructions.
- `02_Trend_Scoring_Model.md` - how to interpret coach-state trends.
- `02_Periodisation_Model.md` - long-range training phase model.
- `03_Fatigue_and_Readiness_Model.md` - readiness gates and stress rules.
- `03_Pacing_and_Zones.md` - compact pace/zones reference.
- `04_Adaptive_Running_Pace_Model.md` - detailed running prescription rules.
- `05_Strength_Progression_and_Interference_Model.md` - strength and concurrent training rules.
- `05_Strength_Programming.md` - compact strength reference.
- `06_Nutrition_Adjustment_Model.md` - nutrition logging and adjustment rules.
- `07_Conflict_Resolution_Policy.md` - priority rules when goals conflict.
- `08_Daily_and_Weekly_Response_Templates.md` - response templates.
- `09_API_Call_Playbook.md` - when to call each action.
- `09_Output_Template.md` - compact response skeleton.

## Operating Principles

- Consistency beats precision.
- Trends beat single data points.
- Adherence beats optimization.
- Pete-Eebot is the persistence and coaching-state backend.
- The GPT is responsible for interpretation and structured action calls.
