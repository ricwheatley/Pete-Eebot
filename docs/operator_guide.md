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

Supported deployment profile today: run the application natively from `/opt/myapp/shared/venv` on Ubuntu, with Postgres reachable from the host. Docker Compose is supported only for Postgres; there is no supported Pete-Eebot application container image.

## 1. Mental Model

The important operating concepts are:

- `training_plans`: one row per generated plan block
- `training_plan_weeks`: one row per week within a plan
- `training_plan_workouts`: scheduled sessions with canonical baseline and effective/exported prescriptions
- `plan_readiness_adjustments`: readiness decision/audit ledger for each plan week
- `training_max`: the latest row per `lift_code` drives weight targets during plan generation
- `exercise_programming_metadata`: Pete-owned programming metadata used to choose assistance and core exercises
- `wger_exercise`: the local exercise catalogue used for IDs, names, categories, and export
- `wger_export_log`: record of what was exported to wger
- `nutrition_log`: immutable approximate macro events supplied by the GPT layer; Postgres is the source of truth

Current plan generation behaviour:

- `pete lets-begin` creates a 1-week strength-test plan and exports week 1.
- `pete plan` creates a 4-week 5/3/1 block and exports week 1.
- CLI, API, and browser-console standard plan requests all default to 4 weeks. Other explicit durations are rejected before job creation; they are not coerced.
- A newly generated plan automatically deactivates any previously active plan.
- Assistance and core selections are partly random. Generating twice is not guaranteed to produce the same accessory mix.
- Weight targets are calculated from the latest `training_max` rows. If a lift has no TM, the plan still generates but target kg values can be blank.

Weekly automation behaviour:

For unified planner internals (context assembly, stress budget, constraint catalog, and decision trace semantics), see `docs/unified_global_planner.md`.

Planner experiments are gated by feature flags. See `docs/planner_feature_flags.md` for safe defaults, override syntax, audit-log checks, and rollback steps.

- the Sunday review path validates the upcoming week
- if the active plan is at its rollover point, Pete creates the next plan block
- otherwise it re-exports the upcoming active week to wger
- the current rollover decision is based on active plan dates and length, not on the `training_cycle` table
- readiness assessment is non-mutating; application is transactional and derives effective sets/RIR from the stored baseline

## 2. First-Time Setup

### 2.1 Environment

Copy `.env.sample` to `.env` and fill in:

- Telegram: `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`
- Withings: `WITHINGS_CLIENT_ID`, `WITHINGS_CLIENT_SECRET`, `WITHINGS_REDIRECT_URI`, `WITHINGS_REFRESH_TOKEN`
- Dropbox: `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`, `DROPBOX_HEALTH_METRICS_DIR`, `DROPBOX_WORKOUTS_DIR`
- wger: `WGER_API_KEY`
- Postgres: either `DATABASE_URL` alone or `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, optional `POSTGRES_PORT`, and `POSTGRES_DB`
- API/Webhook if you use them: `PETEEEBOT_API_KEY`, trusted-proxy CIDRs,
  `GITHUB_WEBHOOK_SECRET`, immutable GitHub repository ID, exact deploy ref,
  expected Git remote URL, webhook body bound, and `DEPLOY_SCRIPT_PATH`
- Nutrition logging: `USER_TIMEZONE` controls local-date assignment when GPT macro logs omit a timestamp

Notes:

- `DATABASE_URL` is authoritative when present; otherwise the settings layer builds a percent-encoded URL from the complete `POSTGRES_*` set
- if both database sources are present they must describe the same decoded user, password, effective host, port, and database; partial or conflicting component configuration fails startup
- `DB_HOST_OVERRIDE` is an optional typed replacement for `POSTGRES_HOST` in component mode
- the API now fails closed if `PETEEEBOT_API_KEY` is not set
- the webhook/deployer fail closed if the HMAC secret, immutable repository ID,
  expected remote URL, or deploy script is unset

### 2.2 Python Environment

Windows:

```powershell
uv sync --frozen
```

Ubuntu production:

```bash
python3 -m venv /opt/myapp/shared/venv
/opt/myapp/shared/uv-tool/bin/uv lock --project /opt/myapp/current --check
UV_PROJECT_ENVIRONMENT=/opt/myapp/shared/venv \
  /opt/myapp/shared/uv-tool/bin/uv sync --project /opt/myapp/current --frozen --no-dev --no-editable
/opt/myapp/shared/uv-tool/bin/uv pip check --python /opt/myapp/shared/venv/bin/python
```

Provision the required uv 0.12.5 tool environment separately as documented in
`docs/venv_setup.md`. Do not regenerate `uv.lock` on the production host.

### 2.3 Database

For a new database, run the authoritative migration history.

Docker path for local Postgres only:

```bash
docker compose up -d db
```

Schema status, upgrade, and verification:

```bash
pete-schema status
pete-schema upgrade
pete-schema verify
```

The runner uses `DATABASE_URL` or complete `POSTGRES_*` configuration. Never run
individual migration files. Existing installations without a ledger must follow
the verified adoption procedure in `docs/schema_management.md`.

### 2.4 OAuth and Credential Sanity Check

Withings:

```bash
pete withings-auth
pete withings-code  # paste the short-lived code at the hidden prompt
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
- missing `exercise_programming_metadata` rows with `difficulty = 0`
- first-run default ratings and role flags from `pete_e/domain/schedule_rules.py`

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
pete logs API 100
pete logs JOB 100
```

Logs are JSON lines in production. Use `docs/logging_observability.md` for the field schema and request/job triage workflow.

Current and recent command jobs are visible in the browser console at `/console/jobs`. Use it after running sync, plan generation, weekly review, strength-test start, message resend, or deploy-triggered workflows to confirm status, requester, auth scheme, timestamps, exit code, and redacted output summaries. Search `/console/history` when you need the durable audit trail for request ID, job ID, user, auth scheme, command, outcome, and safe summary; structured `AUDIT` logs remain a secondary timeline.

### 3.2 Daily Operation

Standard daily ingest:

```bash
pete sync --days 1
```

`pete sync` participates in the same database-backed high-risk operation lock as the API and console command paths, so cron and manual CLI syncs will not overlap with an active API/console sync, plan generation, message resend, or deploy job.

Sync retries use Tenacity and return a structured failed sync result after exhaustion, including the attempt count, final source statuses, failed sources, run label, and undelivered alerts. The final underlying exception is logged with its traceback for diagnosis; it is not allowed to escape past the sync-result contract.

Withings-only branch:

```bash
pete withings-sync --days 7
```

Apple ingest only:

```bash
pete ingest-apple
```

Apple Health imports use Dropbox `client_modified` timestamps as an exclusive
checkpoint. Files are processed in timestamp order, with Dropbox path as a
deterministic tie-breaker. All files sharing a timestamp form one checkpoint
group: the checkpoint advances past that timestamp only when every discovered
file in the group was handled.

An unreadable download, malformed JSON/ZIP, or parser failure is reported as
`Apple Health=partial` when another file was committed, or
`Apple Health=failed` when none was committed. The result and logs identify the
file path, modification time, stage, and a bounded error reason; health payload
contents are not logged. The checkpoint remains strictly before the earliest
failed timestamp, so the failed file and any later successfully upserted files
are eligible for the next run. Apple metric and workout writes use their
natural conflict keys, so this replay updates or ignores existing rows instead
of duplicating them.

The parser remains best-effort within a structurally valid export: it writes
valid rows and counts invalid rows by section. Any non-zero invalid-row count
marks the file and run as `partial` and holds the same watermark, so correcting
the export can recover the omitted rows without duplicating the valid rows.

To retry, correct or replace the Dropbox export and ensure its
`client_modified` value is later than the last committed checkpoint, then run
`pete ingest-apple` once. Check `/console/jobs`, the command response's
`failure_details` and `alerts`, or logs for the failed path and stage. A
database-write, checkpoint-write, or commit failure rolls back both health data
and checkpoint changes for that run. There is no quarantine table: a file stops
blocking the watermark only after it can be handled successfully. Dropbox
cannot reveal a file that first appears later with a `client_modified` value at
or before an already committed checkpoint; replace such a file so Dropbox gives
it a newer modification time.

Build a morning report:

```bash
pete morning-report
pete morning-report --send
pete morning-report --date 2026-03-31
```

The browser console exposes the same daily workflow under `/console/operations`.
Use **Preview Morning Report** to generate the current report without sending, or
set **Date override** for the same `YYYY-MM-DD` override as
`pete morning-report --date`. Use **Send Morning Report** only after typing
`SEND MORNING REPORT`.
Failures show request and job IDs; use those IDs in `/console/jobs`,
`/console/history`, or `/console/logs` when triaging.

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

The browser console exposes the weekly/cycle workflows under
`/console/operations`.

- **Run Sunday Review** starts `python -m scripts.run_sunday_review` only after
  an operator types `RUN SUNDAY REVIEW`.
- **Start Strength Test Week** starts `pete lets-begin --start-date
  YYYY-MM-DD` only after an operator enters a `YYYY-MM-DD` start date, types the
  same date again in **Confirm start date**, and types `BEGIN STRENGTH TEST`.

Both web commands require an `operator` or `owner` browser session plus a valid
CSRF token. They create durable job rows, write command audit history, and use
the shared job-service overlap lock, so they cannot run at the same time as
sync, plan generation, message resend, deploy, or another high-risk command.

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
5 7 * * *  cd /opt/myapp/current && set -a && . /opt/myapp/shared/.env && set +a && /opt/myapp/shared/venv/bin/pete sync --days 1 --retries 3 >> /var/log/pete_eebot/pete_history.log 2>&1
10 7 * * * cd /opt/myapp/current && set -a && . /opt/myapp/shared/.env && set +a && /opt/myapp/shared/venv/bin/pete morning-report --send >> /var/log/pete_eebot/pete_history.log 2>&1
25 16 * * 0  cd /opt/myapp/current && set -a && . /opt/myapp/shared/.env && set +a && /opt/myapp/shared/venv/bin/python3 -m scripts.run_sunday_review >> /var/log/pete_eebot/pete_history.log 2>&1
30 20 * * 0  cd /opt/myapp/current && set -a && . /opt/myapp/shared/.env && set +a && /opt/myapp/shared/venv/bin/pete message --plan --send >> /var/log/pete_eebot/pete_history.log 2>&1
* * * * *  cd /opt/myapp/current && set -a && . /opt/myapp/shared/.env && set +a && /opt/myapp/shared/venv/bin/pete telegram --listen-once --limit 5 --timeout 25 >> /var/log/pete_eebot/pete_history.log 2>&1
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
       tpw.baseline_sets,
       tpw.sets,
       tpw.reps,
       tpw.percent_1rm,
       tpw.target_weight_kg,
       tpw.baseline_rir,
       tpw.rir,
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

- WGER sync keeps the catalogue aligned with WGER
- `exercise_programming_metadata` stores Pete-owned ratings and role eligibility
- the factory samples 2 assistance exercises per lifting day from rows rated `1` through the current adaptive cap
- `difficulty = 0` excludes an exercise from generated plans

Inspect current assistance candidates:

```sql
SELECT epm.exercise_id,
       ex.name,
       epm.difficulty,
       epm.eligible_bench_assistance,
       epm.eligible_squat_assistance,
       epm.eligible_ohp_assistance,
       epm.eligible_deadlift_assistance
FROM exercise_programming_metadata epm
JOIN wger_exercise ex ON ex.id = epm.exercise_id
WHERE epm.eligible_bench_assistance
   OR epm.eligible_squat_assistance
   OR epm.eligible_ohp_assistance
   OR epm.eligible_deadlift_assistance
ORDER BY epm.difficulty, ex.name;
```

Add a new assistance movement:

```sql
UPDATE exercise_programming_metadata
SET difficulty = <difficulty_1_to_10>,
    eligible_squat_assistance = true,
    metadata_source = 'operator',
    updated_at = now()
WHERE exercise_id = <assistance_exercise_id>;
```

Remove one:

```sql
UPDATE exercise_programming_metadata
SET difficulty = 0
WHERE exercise_id = <exercise_id>;
```

Important:

- this changes future plan generation, not already persisted workouts
- because assistance selection is random, adding one exercise does not guarantee it appears every week
- the adaptive cap starts at `2` and is stored in `exercise_difficulty_unlock_state`
- if you want a fixed accessory prescription, change `PlanFactory` instead of just editing the pool

### 8.4 Change Core Movements

Core selection uses the same operator-managed metadata table.

The actual resolution order is:

1. `exercise_programming_metadata` rows with `eligible_core = true`
2. only rows with `difficulty BETWEEN 1 AND current_cap`
3. if no metadata candidates exist, the hard-coded curated defaults are used as a fail-closed fallback

That means WGER categories such as `Abs` are not enough to make an exercise programmable.

Safe operator options:

#### Option A: manage `exercise_programming_metadata` directly

Inspect it:

```sql
SELECT epm.exercise_id, ex.name, epm.difficulty
FROM exercise_programming_metadata epm
JOIN wger_exercise ex ON ex.id = epm.exercise_id
WHERE epm.eligible_core
ORDER BY epm.difficulty, ex.name;
```

Add a core exercise:

```sql
UPDATE exercise_programming_metadata
SET difficulty = <difficulty_1_to_10>,
    eligible_core = true,
    metadata_source = 'operator',
    updated_at = now()
WHERE exercise_id = <core_exercise_id>;
```

Remove one:

```sql
UPDATE exercise_programming_metadata
SET difficulty = 0,
    updated_at = now()
WHERE exercise_id = <core_exercise_id>;
```

This is the cleanest DB-backed way to control future core selection.

#### Option B: change the hard-coded default core pool

Edit `DEFAULT_CORE_POOL_DATA` in `pete_e/domain/schedule_rules.py`.

This is the most reliable route if you want predictable behaviour.

You can still inspect category candidates before adding safe choices to `exercise_programming_metadata`:

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

The current `sp_metrics_overview` migration history hard-codes the existing big four exercise IDs:

- squat `615`
- bench `73`
- deadlift `184`
- OHP `566`

If you replace those lifts system-wide and still want metrics output to show the new lifts, you must:

1. add a new ordered migration that replaces `sp_metrics_overview`
2. add its checksum and revision to `migrations/manifest.json`
3. test previous-to-head, then deploy through `pete-schema upgrade`

Example deployment route:

```bash
pete-schema upgrade
pete-schema verify
```

Never edit or reapply an already-recorded migration. Function changes are forward
migrations and receive the same checksum, backup, and rollout controls as tables.

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
3. add or update the matching `exercise_programming_metadata` row if it should be programmable

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
4. apply your `INSERT`, `UPDATE`, or `DELETE`; for an intentional strength prescription change, update `baseline_sets`/`baseline_rir` and effective `sets`/`rir` together
5. refresh `plan_muscle_volume` if analytics depend on the changed rows
6. if needed, re-export the week to wger

Quick export before editing:

```bash
pete db "SELECT * FROM training_plan_workouts WHERE week_id = <week_id>" --json-file week_backup.json
```

If you need to push the edited week back out, the cleanest operator route is usually to run the weekly review or invoke the relevant export path through code. Pete's automated paths use force overwrite to reassess idempotently and resend/replace the wger routine; force does not compound the readiness adjustment. See `docs/readiness_adjustments.md` for baseline, audit, and migration semantics.

## 11. API Operations

Start the API:

```bash
uvicorn pete_e.api:app --host 127.0.0.1 --port 8000
```

For production internet exposure, bind the app to localhost or a private
interface behind the TLS reverse proxy. Do not expose the Uvicorn port directly
to the public internet.

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

API responses include correlation headers:

- send `X-Correlation-ID` or `X-Request-ID` from clients when you have one
- if omitted, the API generates one
- responses include both `X-Correlation-ID` and `X-Request-ID`

Error responses use this envelope:

```json
{
  "error": {
    "code": "rate_limited",
    "message": "Rate limit exceeded for sync",
    "correlation_id": "example-request-id",
    "details": {
      "operation": "sync",
      "retry_after_seconds": 42
    }
  }
}
```

Command protection defaults (stored atomically in PostgreSQL and shared across
workers/restarts):

- command rate limit: `PETEEEBOT_COMMAND_RATE_LIMIT_MAX_REQUESTS=10` per `PETEEEBOT_COMMAND_RATE_LIMIT_WINDOW_SECONDS=60`
- broader per-operation limit multiplier: `PETEEEBOT_COMMAND_RATE_LIMIT_GLOBAL_MULTIPLIER=5`
- sync timeout: `PETEEEBOT_SYNC_TIMEOUT_SECONDS=300`, also overridable per request with `POST /sync?...&timeout=300`
- plan/deploy subprocess timeout: `PETEEEBOT_PROCESS_TIMEOUT_SECONDS=900`, with plan overridable per request using `timeout=`

Webhook requirements:

- `GITHUB_WEBHOOK_SECRET` must be configured
- `PETEEEBOT_GITHUB_REPOSITORY_ID=1044067254` identifies this repository immutably
- `PETEEEBOT_GITHUB_DEPLOY_REF=refs/heads/main` is the only allowed ref
- `PETEEEBOT_DEPLOY_GIT_REMOTE_URL` must exactly match `git remote get-url origin`
- `X-GitHub-Delivery` and the signed repository/event/ref/SHA identity are
  persisted uniquely before job dispatch
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

### You edited `exercise_programming_metadata` but the plan did not change

Cause:

- you changed metadata after the plan was already generated
- or the exercise is rated above the current adaptive cap in `exercise_difficulty_unlock_state`

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
- `migrations/manifest.json`
- `docs/schema_management.md`

DB tables you will most likely touch:

- `training_plans`
- `training_plan_weeks`
- `training_plan_workouts`
- `training_max`
- `strength_test_result`
- `exercise_programming_metadata`
- `exercise_difficulty_unlock_state`
- `wger_exercise`
- `wger_category`
- `wger_export_log`
- `plan_readiness_adjustments`

## 14. Practical Default Advice

If you only remember three operating rules, use these:

1. Change the DB for one-off plan edits. Change the code for generator behaviour.
2. Update `training_max` before generating blocks if you care about target kg values.
3. When replacing the canonical lifts system-wide, update both `schedule_rules.py` and the SQL function surfaces that still encode the current big four.
