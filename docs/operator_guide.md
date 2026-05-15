# Pete Eebot Operator Guide

This guide is for the person running Pete Eebot as an operator, not just as a developer. It covers:

- first-time setup
- routine daily and weekly operations
- the command surfaces you will actually use
- how the training plan engine is wired
- how to change weekly workout parameters under the unified globally aware planner, including Blaze, runs, assistance work, core work, and main lifts
- when to make a database change vs a code change

Pete Eebot is a Python application with Postgres as its source of truth. The practical control surfaces are:

- the `pete` CLI
- the Postgres database
- the Telegram listener
- the optional FastAPI service

Supported deployment profile today: run the application natively from a Python virtual environment on Linux/Raspberry Pi, with Postgres available as a service. Docker Compose is supported only as a local Postgres helper; there is no supported Pete-Eebot application container image.

## 1. Mental Model

The important operating concepts are:

- `training_plans`: one row per generated plan block
- `training_plan_weeks`: one row per week within a plan
- `training_plan_workouts`: the actual scheduled sessions
- `training_max`: the latest row per `lift_code` drives weight targets during plan generation
- `assistance_pool`: the pool used to randomly choose assistance exercises for each main lift
- `wger_exercise`: the local exercise catalogue used for IDs, names, categories, and export
- `wger_export_log`: record of what was exported to wger
- `nutrition_log`: immutable approximate macro events supplied by the GPT layer; Postgres is the source of truth

Current plan generation behaviour:

- `pete lets-begin` creates a 1-week strength-test plan and exports week 1.
- `pete plan` creates a 4-week 5/3/1 block and exports week 1.
- A newly generated plan automatically deactivates any previously active plan.
- Assistance and core selections are partly random. Generating twice is not guaranteed to produce the same accessory mix.
- Weight targets are calculated from the latest `training_max` rows. If a lift has no TM, the plan still generates but target kg values can be blank.

Weekly automation behaviour:

For unified planner internals (context assembly, stress budget, constraint catalog, and decision trace semantics), see `docs/unified_global_planner.md`.

- the Sunday review path validates the upcoming week
- if the active plan is at its rollover point, Pete creates the next plan block
- otherwise it re-exports the upcoming active week to wger
- the current rollover decision is based on active plan dates and length, not on the `training_cycle` table

## 2. First-Time Setup

### 2.1 Environment

Copy `.env.sample` to `.env` and fill in:

- Telegram: `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`
- Withings: `WITHINGS_CLIENT_ID`, `WITHINGS_CLIENT_SECRET`, `WITHINGS_REDIRECT_URI`, `WITHINGS_REFRESH_TOKEN`
- Dropbox: `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`, `DROPBOX_HEALTH_METRICS_DIR`, `DROPBOX_WORKOUTS_DIR`
- wger: `WGER_API_KEY`
- Postgres: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`
- API/Webhook if you use them: `PETEEEBOT_API_KEY`, `GITHUB_WEBHOOK_SECRET`, `DEPLOY_SCRIPT_PATH`
- Nutrition logging: `USER_TIMEZONE` controls local-date assignment when GPT macro logs omit a timestamp

Notes:

- the settings layer builds `DATABASE_URL` from the `POSTGRES_*` values
- the API now fails closed if `PETEEEBOT_API_KEY` is not set
- the webhook now refuses to run if `GITHUB_WEBHOOK_SECRET` or `DEPLOY_SCRIPT_PATH` are unset

### 2.2 Python Environment

Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .
```

Linux / Raspberry Pi:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .
```

### 2.3 Database

For a new database, apply `init-db/schema.sql`.

Docker path for local Postgres only:

```bash
docker compose up -d db
```

Manual Postgres path:

```bash
psql "$DATABASE_URL" -f init-db/schema.sql
```

For an existing database, apply the incremental migration before relying on the new hardening features:

```bash
psql "$DATABASE_URL" -f migrations/20260401_harden_plan_generation.sql
```

### 2.4 OAuth and Credential Sanity Check

Withings:

```bash
pete withings-auth
pete withings-code <code-from-redirect>
pete refresh-withings
```

Dropbox and Withings local sanity check:

```bash
python -m scripts.check_auth
```

### 2.5 Seed the Exercise Catalogue

The local `wger_exercise` catalogue should exist before you start editing plans by exercise ID.

```bash
python -m scripts.sync_wger_catalog
```

This refreshes the catalogue and seeds:

- `wger_exercise.is_main_lift`
- the `assistance_pool` rows from `pete_e/domain/schedule_rules.py`

### 2.6 Seed Training Maxes

Pete Eebot uses the latest TM per `lift_code`. The current built-in lift codes are:

- `bench`
- `squat`
- `ohp`
- `deadlift`

Example:

```sql
INSERT INTO training_max (lift_code, tm_kg, source, measured_at)
VALUES
  ('bench', 95.0, 'manual', CURRENT_DATE),
  ('squat', 140.0, 'manual', CURRENT_DATE),
  ('ohp', 62.5, 'manual', CURRENT_DATE),
  ('deadlift', 180.0, 'manual', CURRENT_DATE)
ON CONFLICT DO NOTHING;
```

## 3. Routine Operations

### 3.1 Health Checks

Quick dependency check:

```bash
pete status
```

View recent logs:

```bash
pete logs
pete logs SYNC 100
pete logs PLAN 100
```

### 3.2 Daily Operation

Standard daily ingest:

```bash
pete sync --days 1
```

Withings-only branch:

```bash
pete withings-sync --days 7
```

Apple ingest only:

```bash
pete ingest-apple
```

Build a morning report:

```bash
pete morning-report
pete morning-report --send
pete morning-report --date 2026-03-31
```

Build and optionally send the daily narrative:

```bash
pete message --summary
pete message --summary --send
pete message --trainer
pete message --trainer --send
```

### 3.3 Weekly Operation

Create and export the next 4-week block:

```bash
pete plan --start-date 2026-04-06
```

Start a new cycle with the strength-test week:

```bash
pete lets-begin --start-date 2026-04-06
```

Important:

- `lets-begin` does not create a full 13-week cycle in one go
- it creates a 1-week strength-test plan and exports week 1
- the next Sunday review can then roll that into the following 4-week block

Run the weekly review automation:

```bash
python -m scripts.run_sunday_review
```

Build and optionally send the weekly plan message:

```bash
pete message --plan
pete message --plan --send
```

### 3.4 Telegram Operation

The Telegram listener is short-lived. It is designed to be called repeatedly by cron or another scheduler.

```bash
pete telegram --listen-once --limit 5 --timeout 25
```

Supported bot commands:

- `/summary`
- `/sync`
- `/lets-begin`

### 3.5 Useful Query and Metrics Commands

Ad hoc SQL:

```bash
pete db "SELECT * FROM training_plans ORDER BY id DESC LIMIT 5"
```

Metrics overview:

```bash
pete metrics
pete metrics 2026-03-31
pete metrics 2026-03-24 2026-03-31
```

## 4. Recommended Scheduler Layout

A practical cron layout is:

```cron
5 7 * * *  cd /home/pi/Pete-Eebot && /home/pi/.local/bin/pete sync --days 1 --retries 3 >> logs/cron.log 2>&1
10 7 * * * cd /home/pi/Pete-Eebot && /home/pi/.local/bin/pete morning-report --send >> logs/cron.log 2>&1
25 16 * * 0  cd /home/pi/Pete-Eebot && python3 -m scripts.run_sunday_review >> logs/cron.log 2>&1
30 20 * * 0  cd /home/pi/Pete-Eebot && /home/pi/.local/bin/pete message --plan --send >> logs/cron.log 2>&1
* * * * *  cd /home/pi/Pete-Eebot && /home/pi/.local/bin/pete telegram --listen-once --limit 5 --timeout 25 >> logs/cron.log 2>&1
```

## 5. How the Plan Generator Works

The key code lives in:

- `pete_e/domain/schedule_rules.py`
- `pete_e/domain/plan_factory.py`
- `pete_e/application/services.py`

Current defaults:

- main-lift days: Monday, Tuesday, Thursday, Friday
- main lifts: bench, squat, OHP, deadlift
- Blaze sessions are added from `BLAZE_TIMES`
- 4-week 5/3/1 blocks are built from `_FIVE_THREE_ONE_TEMPLATE`
- week 4 is the deload week
- two assistance exercises are sampled from the pool for each main lift day
- one core exercise is sampled for each main lift day

Because assistance and core choices are random samples, these are not deterministic:

- assistance mix can change between plan generations
- core movement selection can change between plan generations

If you want reproducibility, you need to seed randomness in code or stop using random selection.

## 6. Operator Rule: DB Edit or Code Edit?

Use a database edit when:

- you want to change the current active plan only
- you want a one-off change for this week or this block
- you want to add or remove a single workout without changing the generator
- you want to update training max values
- you want to change assistance pool membership without changing scheduling logic

Use a code edit when:

- you want every newly generated plan to change
- you want to change unified run-strength constraints, stress budgeting, or cross-modality scheduling rules
- you want to change Blaze defaults
- you want to change the 5/3/1 percentages, rest timing, or accessory schemes
- you want to replace the core main lifts system-wide
- you want recurring runs or cardio sessions to appear automatically

## 7. Inspecting the Current Plan

Find the active plan:

```sql
SELECT id, start_date, weeks, is_active, created_at
FROM training_plans
WHERE is_active = true
ORDER BY id DESC
LIMIT 1;
```

View its weeks:

```sql
SELECT id, plan_id, week_number, is_test
FROM training_plan_weeks
WHERE plan_id = <plan_id>
ORDER BY week_number;
```

View all workouts in a given week:

```sql
SELECT tpw.id,
       tw.week_number,
       tpw.day_of_week,
       tpw.scheduled_time,
       tpw.exercise_id,
       e.name AS exercise_name,
       tpw.sets,
       tpw.reps,
       tpw.percent_1rm,
       tpw.target_weight_kg,
       tpw.rir_cue,
       tpw.is_cardio
FROM training_plan_workouts tpw
JOIN training_plan_weeks tw ON tw.id = tpw.week_id
JOIN wger_exercise e ON e.id = tpw.exercise_id
WHERE tw.plan_id = <plan_id>
  AND tw.week_number = <week_number>
ORDER BY tpw.day_of_week, tpw.scheduled_time NULLS LAST, tpw.id;
```

## 8. Adjusting Weekly Workout Parameters

### 8.1 Remove Blaze

There are two distinct cases.

#### Remove Blaze from future generated plans

Edit `pete_e/domain/schedule_rules.py`.

Current behaviour is driven by:

- `BLAZE_ID = 1630`
- `BLAZE_TIMES = { ... }`

Options:

- remove specific weekdays from `BLAZE_TIMES`
- set `BLAZE_TIMES = {}` to remove Blaze entirely

This affects:

- new 4-week 5/3/1 blocks
- new strength-test weeks

After the code change:

1. regenerate the next plan with `pete plan` or `pete lets-begin`
2. if you changed only code and kept the existing active plan, nothing already in the DB will change

#### Remove Blaze from the current active plan only

Delete the corresponding rows from `training_plan_workouts`.

Example for the active plan:

```sql
DELETE FROM training_plan_workouts tpw
USING training_plan_weeks tw, training_plans tp
WHERE tpw.week_id = tw.id
  AND tw.plan_id = tp.id
  AND tp.is_active = true
  AND tpw.exercise_id = 1630;
```

If you want to remove Blaze from just one week:

```sql
DELETE FROM training_plan_workouts tpw
USING training_plan_weeks tw, training_plans tp
WHERE tpw.week_id = tw.id
  AND tw.plan_id = tp.id
  AND tp.is_active = true
  AND tw.week_number = 2
  AND tpw.exercise_id = 1630;
```

After manual edits to planned workouts, refresh the plan view if you use plan volume analytics:

```sql
REFRESH MATERIALIZED VIEW plan_muscle_volume;
```

### 8.2 Add Runs or Other Cardio

Again, decide whether this is one-off or systematic.

#### Add a run to the current active plan only

1. find a suitable `exercise_id` from `wger_exercise`
2. find the target `week_id`
3. insert a new row into `training_plan_workouts`

Find likely run exercises:

```sql
SELECT id, name
FROM wger_exercise
WHERE name ILIKE '%run%'
   OR name ILIKE '%jog%'
   OR name ILIKE '%treadmill%'
ORDER BY name;
```

Insert the run:

```sql
INSERT INTO training_plan_workouts (
    week_id,
    day_of_week,
    exercise_id,
    sets,
    reps,
    rir,
    percent_1rm,
    target_weight_kg,
    rir_cue,
    scheduled_time,
    is_cardio
)
VALUES (
    <week_id>,
    3,
    <run_exercise_id>,
    1,
    1,
    NULL,
    NULL,
    NULL,
    NULL,
    '18:30:00',
    true
);
```

Notes:

- for cardio rows, `sets=1` and `reps=1` is the existing convention
- duration is not stored in `training_plan_workouts`
- wger comments for cardio are limited compared with the main lift annotations

#### Add recurring runs to every newly generated plan

This is a code change in `pete_e/domain/plan_factory.py`.

The existing factory already inserts Blaze rows before lift rows. The cleanest pattern is to add another scheduling block in:

- `create_531_block_plan`
- and, if needed, `create_strength_test_plan`

Typical operator-safe implementation:

1. add a new constant in `pete_e/domain/schedule_rules.py`, for example `RUN_TIMES`
2. loop over it in `PlanFactory`
3. append cardio rows using the run exercise ID

If you want the run to appear on only some weeks, branch on `week_num`.

### 8.3 Change Assistance Lifts

This is mostly a database job.

Current behaviour:

- each main lift maps to a pool of assistance exercise IDs
- the factory samples 2 exercises from that pool for each lifting day
- if the DB pool is empty, the code falls back to the hard-coded `ASSISTANCE_POOL_DATA`

Inspect the current pool:

```sql
SELECT ap.main_exercise_id,
       main.name AS main_name,
       ap.assistance_exercise_id,
       assist.name AS assistance_name
FROM assistance_pool ap
JOIN wger_exercise main ON main.id = ap.main_exercise_id
JOIN wger_exercise assist ON assist.id = ap.assistance_exercise_id
ORDER BY main.name, assist.name;
```

Add a new assistance movement:

```sql
INSERT INTO assistance_pool (main_exercise_id, assistance_exercise_id)
VALUES (<main_lift_id>, <assistance_exercise_id>)
ON CONFLICT DO NOTHING;
```

Remove one:

```sql
DELETE FROM assistance_pool
WHERE main_exercise_id = <main_lift_id>
  AND assistance_exercise_id = <assistance_exercise_id>;
```

Important:

- this changes future plan generation, not already persisted workouts
- because assistance selection is random, adding one exercise does not guarantee it appears every week
- if you want a fixed accessory prescription, change `PlanFactory` instead of just editing the pool

### 8.4 Change Core Movements

Core selection is a little less clean than assistance selection.

The actual resolution order is:

1. `core_pool` in Postgres
2. category-based fallback from `wger_exercise` / `wger_category`
3. if both return nothing, `DEFAULT_CORE_POOL_IDS` in `pete_e/domain/schedule_rules.py`

That means there is now a clean DB-backed control surface for core work.

Safe operator options:

#### Option A: manage `core_pool` directly

Inspect it:

```sql
SELECT cp.exercise_id, ex.name
FROM core_pool cp
JOIN wger_exercise ex ON ex.id = cp.exercise_id
ORDER BY ex.name;
```

Add a core exercise:

```sql
INSERT INTO core_pool (exercise_id)
VALUES (<core_exercise_id>)
ON CONFLICT DO NOTHING;
```

Remove one:

```sql
DELETE FROM core_pool
WHERE exercise_id = <core_exercise_id>;
```

This is the cleanest DB-backed way to control future core selection.

#### Option B: change the hard-coded default core pool

Edit `DEFAULT_CORE_POOL_IDS` in `pete_e/domain/schedule_rules.py`.

This is the most reliable route if you want predictable behaviour.

#### Option C: use the exercise catalogue categories

If your desired core exercises exist in `wger_exercise`, make sure their category is something like `Core` or `Abs`, then newly generated plans can pick them up through the fallback path.

Find current core-category candidates:

```sql
SELECT ex.id, ex.name, cat.name AS category
FROM wger_exercise ex
JOIN wger_category cat ON cat.id = ex.category_id
WHERE LOWER(cat.name) LIKE 'core%'
   OR LOWER(cat.name) LIKE 'abs%'
ORDER BY ex.name;
```

If you want a manual, deterministic current-plan change, edit the already persisted rows in `training_plan_workouts`.

### 8.5 Change Main Lifts or the Weekly Split

This is a code change, not just a DB tweak.

If you want to replace one of the canonical lifts, edit `pete_e/domain/schedule_rules.py`:

- `LIFT_CODE_BY_ID`
- `MAIN_LIFT_IDS`
- `MAIN_LIFT_BY_DOW`
- `TEST_WEEK_LIFT_ORDER`
- `TEST_WEEK_PCTS`
- `ASSISTANCE_POOL_DATA`
- `weight_slot_for_day`

Then update the supporting data:

1. make sure the new exercise exists in `wger_exercise`
2. mark it as a main lift if you want the catalogue to reflect reality
3. add matching `training_max` rows for its new `lift_code`

Example:

```sql
UPDATE wger_exercise
SET is_main_lift = true
WHERE id = <new_main_lift_id>;
```

### 8.6 Change Core Lifts System-Wide

If by "core lifts" you mean the main barbell lifts the whole system revolves around, there is one extra step beyond `schedule_rules.py`.

`sp_metrics_overview` in `init-db/schema.sql` currently hard-codes the existing big four exercise IDs:

- squat `615`
- bench `73`
- deadlift `184`
- OHP `566`

If you replace those lifts system-wide and still want metrics output to show the new lifts, you must:

1. edit `init-db/schema.sql`
2. update the `sp_metrics_overview` function definition for the new exercise IDs
3. apply the SQL to the live database

Example deployment route:

```bash
psql "$DATABASE_URL" -f init-db/schema.sql
```

Be careful with this on a live DB. Reapplying the whole schema file may be heavier than needed. On a production database, prefer extracting and running only the updated `CREATE OR REPLACE FUNCTION sp_metrics_overview(...)` statement.

### 8.7 Change Percentages, Deloads, Reps, and Rest Times

Edit `pete_e/domain/schedule_rules.py`:

- `_FIVE_THREE_ONE_TEMPLATE`
- `ASSISTANCE_1`
- `ASSISTANCE_2`
- `CORE_SCHEME`

That file controls:

- week-by-week percentages
- main-set rep schemes
- AMRAP flags
- rest timings
- assistance set and rep defaults
- core set and rep defaults

### 8.8 Change Training Maxes

This is a DB edit.

The generator uses the latest `measured_at` value per `lift_code`.

Inspect current TMs:

```sql
SELECT DISTINCT ON (lift_code)
       lift_code,
       tm_kg,
       source,
       measured_at
FROM training_max
ORDER BY lift_code, measured_at DESC;
```

Add or update a TM:

```sql
INSERT INTO training_max (lift_code, tm_kg, source, measured_at)
VALUES ('bench', 97.5, 'manual-adjustment', CURRENT_DATE)
ON CONFLICT DO NOTHING;
```

Operator note:

- there is a `strength_test_result` table
- after you log the AMRAP test week and run sync, the next block-generation path automatically writes `strength_test_result` rows and upserts `training_max` rows with source `AMRAP_EPLEY`
- if a workout log arrives late or you correct reps/weight and rerun plan generation, Pete updates the same `strength_test_result` / `training_max` rows for that test week
- if you want to override the automatic TM manually, insert a newer `measured_at` row in `training_max`

## 9. Adding New Exercises to the Catalogue

Preferred route:

```bash
python -m scripts.sync_wger_catalog
```

If the exercise exists upstream in wger, that is the cleanest way to get it locally.

If the exercise does not exist upstream and you want a local-only exercise:

1. insert a new `wger_exercise` row with a locally reserved integer ID
2. attach category, equipment, and muscle rows as needed
3. use that ID in `assistance_pool`, `schedule_rules.py`, or `training_plan_workouts`

Example local insert:

```sql
INSERT INTO wger_exercise (id, uuid, name, description, is_main_lift, category_id)
VALUES (
    900001,
    '11111111-1111-1111-1111-111111111111',
    'Steady State Run',
    'Local-only cardio entry used by Pete Eebot planning.',
    false,
    <category_id>
);
```

Practical advice:

- keep local-only IDs in a clearly reserved range such as `900000+`
- document them in the repo if they become part of plan generation
- avoid colliding with upstream wger IDs

## 10. Safe Workflow for Plan Surgery

When changing already persisted workouts:

1. identify the active `plan_id`
2. inspect the target `week_id`
3. export the current rows before editing
4. apply your `INSERT`, `UPDATE`, or `DELETE`
5. refresh `plan_muscle_volume` if analytics depend on the changed rows
6. if needed, re-export the week to wger

Quick export before editing:

```bash
pete db "SELECT * FROM training_plan_workouts WHERE week_id = <week_id>" --json-file week_backup.json
```

If you need to push the edited week back out, the cleanest operator route is usually to run the weekly review or invoke the relevant export path through code. Pete's export services use force-overwrite behaviour for the automated weekly export paths, so replacing an already exported week is expected.

## 11. API Operations

Start the API:

```bash
uvicorn pete_e.api:app --host 0.0.0.0 --port 8000
```

Available endpoints include:

- `GET /`
- `GET /metrics_overview?date=YYYY-MM-DD`
- `GET /plan_for_day?date=YYYY-MM-DD`
- `GET /plan_for_week?start_date=YYYY-MM-DD`
- `GET /status`
- `POST /sync?days=1&retries=3`
- `GET /logs?lines=100`
- `POST /run_pete_plan_async?weeks=4&start_date=YYYY-MM-DD`
- `POST /webhook`

For the full read/command/admin classification, see `docs/api_endpoint_inventory.md`.

Protected endpoints require:

- `X-API-Key: <PETEEEBOT_API_KEY>`

Do not send `PETEEEBOT_API_KEY` as a query parameter. API-key protected routes reject `?api_key=...`; header auth is the supported mechanism.

Webhook requirements:

- `GITHUB_WEBHOOK_SECRET` must be configured
- `DEPLOY_SCRIPT_PATH` must point to an existing script
- GitHub must send a valid `X-Hub-Signature-256`

## 12. Troubleshooting

### A plan generates but target weights are blank

Cause:

- missing `training_max` rows for one or more `lift_code` values

Fix:

- inspect `training_max`
- insert a fresh TM row for the missing lift code

### `pete message --plan` says the active plan has finished

Cause:

- the active plan's `start_date` and `weeks` no longer cover today

Fix:

- generate the next block with `pete plan`
- or run the Sunday review flow

### You edited `assistance_pool` but the plan did not change

Cause:

- you changed the pool after the plan was already generated

Fix:

- regenerate a new plan
- or directly edit `training_plan_workouts` for the current block

### You removed Blaze in code but Blaze is still showing up

Cause:

- the active plan already contains persisted Blaze rows

Fix:

- delete the current Blaze rows from `training_plan_workouts`
- future plan generations will reflect the code change

### You changed the main lifts and metrics still show the old ones

Cause:

- `sp_metrics_overview` still references the old exercise IDs

Fix:

- update the SQL function and apply it to the live DB

### Telegram commands do nothing

Check:

- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT_ID`
- whether `pete telegram --listen-once` is actually being run by cron
- whether the listener offset file is stuck in an unexpected state

The offset file lives beside the main log path and is named `telegram_listener_offset.json`.

## 13. File and Table Reference

Code files you will most likely touch:

- `pete_e/domain/schedule_rules.py`
- `pete_e/domain/plan_factory.py`
- `pete_e/application/services.py`
- `pete_e/application/orchestrator.py`
- `pete_e/cli/messenger.py`
- `pete_e/api.py`
- `init-db/schema.sql`

DB tables you will most likely touch:

- `training_plans`
- `training_plan_weeks`
- `training_plan_workouts`
- `training_max`
- `strength_test_result`
- `assistance_pool`
- `core_pool`
- `wger_exercise`
- `wger_category`
- `wger_export_log`

## 14. Practical Default Advice

If you only remember three operating rules, use these:

1. Change the DB for one-off plan edits. Change the code for generator behaviour.
2. Update `training_max` before generating blocks if you care about target kg values.
3. When replacing the canonical lifts system-wide, update both `schedule_rules.py` and the SQL function surfaces that still encode the current big four.
