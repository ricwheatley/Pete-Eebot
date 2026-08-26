# Incremental maintainability tranches

This document records bounded architecture work and the evidence used to select
it. A tranche should preserve its external contract, add feedback around the
selected boundary, and leave unrelated hotspots for later changes.

## 2026-08-23: weekly narrative metric analysis

### Baseline and candidate ranking

The repository was clean on `main`. Recent changes had concentrated on schema
migrations, durable jobs, edge security, profiles, and the web console. The test
harness already imported the real FastAPI, Starlette, Typer, Click, Pydantic,
psycopg, and other installed dependencies; there was no global framework-module
substitution to remove.

The current measurements confirmed that maintainability debt remained
concentrated:

| Candidate hotspot | Physical lines | C901 findings (maximum) | Branch coverage | Commits in previous 90 days | Tranche assessment |
| --- | ---: | ---: | ---: | ---: | --- |
| `infrastructure/postgres_dal.py` plan persistence | 2,246 | 3 (24) | 33% | 8 | High production and transaction risk; PostgreSQL characterization would make this larger than one safe session. |
| `api_routes/web.py` command operations | 1,845 | 0 | 77% | 10 | High security sensitivity and current churn; repetition exists, but no single extreme-complexity function. |
| `cli/messenger.py` summary commands | 1,558 | 7 (19) | 48% | 8 | Valuable seam, but low branch coverage and mixed IO require a broader characterization tranche. |
| `domain/narrative_builder.py` weekly metric analysis | 1,513 | 4 (34) | 72% | 0 | Highest single-function complexity, pure inputs/outputs, existing snapshots, and a stable extraction boundary. |

Unique direct project-module imports were 6 for the DAL, 12 for web routes, 18
for the CLI, and 8 for the narrative builder. Strict mypy probes (not configured
lanes) found 31 local/109 transitive errors for the DAL, 50/531 for web routes,
32/388 for the CLI, and 2/21 for the original narrative builder. These totals
reinforced the need for a narrow typed boundary rather than a nominal whole-file
type gate.

Repository-wide Ruff C901 scanning found 39 functions over complexity 10. Full
Ruff found two enforceable errors outside the old CI file list. Ruff formatting
would have changed 227 files, so formatting normalization was explicitly excluded.
The real-framework unit/contract run passed 663 tests with 7 skips and measured
66% combined line/branch coverage. Coverage and mypy were not project dependencies,
there was no branch ratchet, and there was no configured type-checking scope. A
strict mypy probe of the narrative builder and its followed imports emitted 21
legacy errors, which was too broad to be an actionable first boundary.

The weekly metric-analysis stage was selected because it offered the largest
bounded complexity reduction with the strongest characterization evidence and
lowest infrastructure risk. The DAL has greater absolute risk, the CLI has more
complex functions, and the web module changes more frequently, but each needs a
larger framework or persistence confidence tranche before extraction.

### Stable behavioral contract

`build_weekly_narrative(metrics) -> str` remains the public interface. Its
contract is:

- use the seven days before the current UTC date and the preceding seven-day
  comparison window;
- preserve the exact empty and quiet-week responses;
- preserve insight order: strength, steps, sleep, muscle composition, Body Age,
  then at most two trend lines;
- preserve the 0.5 percentage-point muscle threshold, Body Age up/down/equal
  wording, missing/invalid body-metric handling, and existing malformed strength
  record error behavior;
- preserve greeting, phrase selection, sentence stitching, and final rendered
  text outside the analysis stage; and
- keep invalid date keys and non-dictionary payloads out of trend samples, cap
  the trend date at yesterday, and preserve trend-line ordering.

Existing output snapshots plus new characterization tests protect this contract.

### Extraction pattern

`domain.weekly_narrative.analyze_weekly_metrics` is the stable internal analysis
interface. It receives the date-keyed payload, an explicit `today`, and three
small collaborators for comparison formatting, trend rendering, and date
parsing. It returns a frozen `WeeklyNarrativeAnalysis` containing ordered
insights. The existing narrative builder remains the presentation adapter: it
owns UTC time selection, randomness, phrases, and sentence stitching.

This is more than a line move:

- the presentation function's cyclomatic complexity fell from 34 to 3;
- the analyzer is complexity 1 and no extracted helper exceeds 5;
- the presentation function now knows only the top-level `days` field, rather
  than ten raw weekly payload keys and their nested shapes;
- the analysis module imports no application, infrastructure, presentation, or
  project utility module; and
- explicit collaborators avoid global state and make each metric policy a pure
  branch-testable function.

Use this pattern for later tranches: characterize the external adapter first,
extract one typed decision stage with explicit collaborators and an immutable
result, and keep IO/framework presentation at the existing boundary.

### Quality ratchets and after measurements

Coverage 7.15.4 and mypy 2.3.1 are locked development dependencies. CI now:

- runs Ruff over `pete_e`, `tests`, and `scripts` rather than a selected file list;
- checks strict mypy for the explicit first scope,
  `pete_e/domain/weekly_narrative.py`;
- measures the combined real-framework unit/contract lane with branch tracing;
- enforces the measured repository baseline of 66%, a non-regression floor rather
  than an aspirational target; and
- enforces 100% combined line/branch coverage for the small pure extracted seam,
  matching its measured 112 statements and 40 branches.

The format check is deliberately limited to the three new tranche source/test
files. The legacy repository-wide 227-file normalization remains separate.

| Measure | Before | After |
| --- | ---: | ---: |
| `build_weekly_narrative` cyclomatic complexity | 34 | 3 |
| Repository C901 findings | 39 | 38 |
| `narrative_builder.py` physical lines | 1,513 | 1,405 |
| Extracted analyzer maximum complexity | n/a | 5 |
| Extracted analyzer branch coverage | n/a | 100% |
| Combined narrative builder/analyzer coverage | 72% legacy module | 74% combined scope |
| Repository line/branch coverage | 66% displayed | 66.26% (66% displayed) |
| Non-database tests | 663 passed | 677 passed |
| Declared incremental mypy errors | no lane | 0 |
| Full intended Ruff errors | 2 | 0 |

## 2026-08-23: Apple Health parser decision stages

### Selection and protected contract

The tranche started from a clean `main` worktree at
`b2faec278fe366ece6a2a3837c0a63ff62690a79`, tracking the same commit on
`origin/main`. The parser was the next documented tranche because one 363-line,
complexity-60 function coupled third-party shape checks, recursive coercion,
eight stream policies, environmental conversion, ordering, and diagnostics.
The writer and ingest coordinator both depend on its raw nine-key dictionary.

`AppleHealthParser.parse(root)` remains the public adapter. It still returns, in
order, `daily_metric_points`, `hr_summaries`, `sleep_summaries`,
`workout_headers`, `workout_hr`, `workout_steps`, `workout_energy`,
`workout_hr_recovery`, and `skipped_row_count`. The existing dataclass names and
fields remain available from `apple_parser`. Missing and falsey timestamps remain
skippable; a non-empty malformed timestamp still raises and aborts parsing. The
adapter still emits at most one `WARN` summary with the same wording and stream
order.

Characterization also pins two surprising legacy decisions rather than repairing
them here: a falsey top-level workout `distance` can fall through to
`walkingRunningDistance`, and a blank source on the first dictionary row of the
preferred workout series prevents later series from supplying a device name.

### Internal boundary

The adapter now delegates to three infrastructure-internal modules:

- `apple_parser_normalization.py` owns strict raw-dictionary/list narrowing,
  timestamp and recursive numeric coercion, unit extraction, heart-rate
  normalisation, and workout environment precedence/conversion;
- `apple_parser_stages.py` owns root recognition, metric/workout discrimination,
  stream-specific row mapping, ordering, and typed outcome assembly; and
- `apple_parser_types.py` owns the output dataclasses, the exact `TypedDict`
  façade, per-stream skipped-row diagnostics, and immutable stage outcomes.

The dependency direction is adapter -> stages -> normalization/types. The
normalization and types modules have no project imports; none of the new modules
imports the ingestor, writer, PostgreSQL, application, CLI, or API, and the graph
is acyclic. Logging remains in the outer adapter.

### Characterization and feedback ratchets

Thirty-six adapter characterizations cover all nine keys, every output
dataclass at value level, accepted and wrong container shapes, falsey versus
malformed timestamps in all eight streams, aliases, recursive values, units,
environment layouts, device selection, ordering, exact skip counts/warnings,
dataclass module identity, and parse-to-writer row mapping. Forty-three direct stage tests cover the pure
recognition, normalization, mapping, and error branches. A deterministic
differential probe of 2,000 generated payloads against the exact pre-extraction
parser found no output, warning, or exception differences.

CI additively includes the three pure modules in strict mypy, checks formatting
only for the existing tranche files and the six changed Apple Python files, and
enforces 100% combined statement/branch coverage for the adapter and typed
boundary. The repository coverage floor remains 66%; the measured unit/contract
result increased without changing that floor.

| Measure | Before | After |
| --- | ---: | ---: |
| Public adapter physical / lexical code lines | 666 / 597 | 81 / 70 |
| Total typed Apple parsing boundary physical / lexical code lines | 666 / 597 | 1,237 / 1,008 |
| `parse` physical span | 363 | 8 |
| Configured C901 findings in parsing boundary | 4 (maximum 60) | 0 (maximum function complexity 6) |
| Strict local parser errors | 22 | 0 |
| Apple parser/boundary branch-aware coverage | 60.4488% | 100% (673 statements, 240 branches) |
| Repository line/branch coverage | 66.2646% | 68.0018% (68% displayed) |
| Unit/contract lane | 677 passed, 7 skipped | 756 passed, 7 skipped |

### Future tranche order

Do not combine these into one change:

1. Completed 2026-08-25: treat `AppleHealthDropboxIngestor._run_ingest` and its
   discovery, transaction, checkpoint, equal-timestamp, retry, alert, and
   partial-file policies as a separate coordinator tranche; none of it moved
   with parser decisions. The measured result is recorded below.
2. Extract the DAL plan-persistence slice behind its existing repository port,
   after raising PostgreSQL integration coverage around transaction rollback,
   active-plan invariants, and mapper failures.
3. Extract one CLI summary/formatting family into a typed application service,
   retaining real Typer contract tests for parsing and exit behavior.
4. Consolidate one web command-operation family behind an application command
   executor after the recent security/job changes stabilize; retain real ASGI,
   CSRF, RBAC, audit, and error-mapping tests.
5. Address the remaining narrative functions separately: trend computation,
   weekly workout formatting, then daily-from-days narrative construction.

Residual risk remains in untyped ingestor/writer dictionary consumption outside
the parsing boundary, the deferred ingest coordinator, the low-covered DAL/CLI
hotspots, and the repository's other legacy C901 findings. The 66% repository
floor is intentionally a non-regression floor and should rise only with a later
remeasured repository baseline.

## 2026-08-25: Apple Health ingest outcome and checkpoint coordination

### Baseline and protected contract

The tranche started from a clean `main` worktree at
`233757d3f242d759b0f5100570a8a85ecadc5708`, tracking the same commit on
`origin/main`. On that branch, the ingestor remained 451 physical lines and
`_run_ingest` remained a 223-line, complexity-21 function. It coupled connection
and writer creation, two Dropbox listings, checkpoint reads, timestamp/path
ordering, equal-timestamp grouping, file IO, parsing, writing, recoverable versus
transaction-fatal failure handling, safe-watermark advancement, commit,
result/alert construction, and logging. Its branch-aware coverage was
85.407725%; the repository unit/contract lane passed 803 tests with 7 skips at
68.662492% coverage.

The public `AppleHealthDropboxIngestor.ingest()` and
`get_last_import_timestamp()` interfaces and the existing domain result/failure
dataclasses remain unchanged. Characterization pins construction before
discovery, both Dropbox listings, exclusive checkpoint boundaries, UTC
normalisation, timestamp then case-insensitive/path ordering, indivisible
equal-timestamp groups, partial-row accounting, safe-watermark blocking, exact
failure stages/reasons and alerts, and the existing transaction distinction:
recoverable file failures may coexist with committed later successes, while a
write, checkpoint-save, or commit failure rolls back the run and returns the
stable empty failed result.

### Typed policy boundary

`infrastructure.apple_ingest_coordinator` now owns frozen source, timestamp-group,
file-outcome, group-outcome, and final-decision facts. Its pure functions merge
and order discovery facts, aggregate failures and row counts, block unsafe
watermarks, and decide checkpoint-save, commit, status, source-failure, and alert
values. The module opens no connection, calls no Dropbox or parser implementation,
writes no rows or checkpoints, logs nothing, sends no alert, and imports no
application, CLI, or API module.

The outer ingestor still owns collaborator construction and every side effect.
It executes one source at a time, records an immutable outcome, asks the pure
policy for the final decision, then performs checkpoint persistence and commit
inside the existing connection context. The dependency direction remains
acyclic: adapter -> coordinator -> domain result type.

### Characterization and feedback ratchets

Seventeen pre-extraction adapter characterizations passed against the original
coordinator. The final focused lane has 53 tests covering no work, checkpoint
filtering, both listings, naive/aware timestamps, path ties, every recoverable
file stage, partial rows, mixed equal-timestamp groups, later success after an
unsafe failure, connection/writer/checkpoint/discovery failures, write/checkpoint/
commit rollback, exact result/alert fields, safe-reason quirks, and event order.
Twelve pure tests cover every line and branch in the decision module. Existing
guarded real-PostgreSQL tests continue to cover checkpoint persistence/replay and
rollback of a health write when checkpoint persistence fails.

CI additively includes the coordinator in strict mypy and its own 100% branch
coverage ratchet. Formatting remains limited to the four changed Apple source/
test files. The repository-wide 233-file formatting delta remains separate, and
the 66% repository coverage floor is unchanged.

| Measure | Before | After |
| --- | ---: | ---: |
| `_run_ingest` physical span / complexity | 223 / 21 | 23 / 3 |
| New/extracted helper maximum complexity | n/a | 5 |
| Repository C901 findings | 39 | 38 |
| Ingestor physical lines | 451 | 424 |
| Ingestor branch-aware coverage | 85.407725% | 96.313364% |
| Pure coordinator branch-aware coverage | n/a | 100% (86 statements, 12 branches) |
| Repository line/branch coverage | 68.662492% | 68.886482% |
| Unit/contract lane | 803 passed, 7 skipped | 838 passed, 7 skipped |
| Declared incremental mypy errors | 0 in 4 files | 0 in 5 files |

The Apple parser's record recognition and nine-key mapping contract, Apple writer
SQL, PostgreSQL schema/DAL work, retry design, and unrelated application/CLI/web
hotspots remain explicitly outside this tranche.

## 2026-08-26: atomic PostgreSQL full-plan persistence

### Baseline and selected boundary

The tranche started from a clean `main` worktree at
`0dcdd2bef926f5e724464707ebec844f86304821`, aligned with `origin/main`.
`postgres_dal.py` had grown to 2,355 physical lines; `save_full_plan` remained a
152-line, complexity-24 method, and the DAL still had three C901 findings with a
maximum of 24. The remeasured unit/contract lane passed 838 tests with 7 skips at
69% displayed branch-aware repository coverage; the DAL measured 34%, with the
entire save span uncovered. A narrow strict probe found 30 errors in the legacy
DAL, while the configured five-file strict scope remained clean.

The method coupled raw payload validation, raw week ordering, workout coercion,
JSON adaptation, runtime index assurance, active-plan transition, three-table
inserts, baseline duplication, commit/rollback, logging, and ID extraction. The
normal runtime path first repaired active rows and ran `CREATE UNIQUE INDEX IF
NOT EXISTS`, although migration `20260401_harden_plan_generation` already owns
that invariant. A real DML-only role could update and insert the plan tables but
failed the old save at that runtime DDL statement.

### Payload-to-row contract

The characterization suite pins this mapping before and after extraction:

| Payload source | Normalization/default/order | Persisted destination |
| --- | --- | --- |
| `start_date` | required non-`None`; otherwise passed through | `training_plans.start_date` |
| `weeks` | any `int`, including `bool`; otherwise `len(plan_weeks)` | `training_plans.weeks` |
| `metadata` | `Json` only when non-`None` | `training_plans.metadata` |
| `plan_weeks` | required non-empty `list`; stable sort by raw `week_number` | insertion order in `training_plan_weeks` |
| week `week_number` / `is_test` | legacy integer coercion / `bool`, default false | `week_number` / `is_test` |
| week `workouts` | falsey means empty; any iterable otherwise; input order retained; each item must be a `dict` | insertion order in `training_plan_workouts` |
| workout IDs/counts | integer coercion for `day_of_week`, `exercise_id`, `sets`, `reps`, and `programmed_difficulty`; only day is payload-required | same-named columns |
| `sets` | one effective value, duplicated at creation | `sets` and `baseline_sets` |
| `rir` / `rir_cue` | raw `rir`; cue falls back to `rir` only when cue is `None` | `rir`, duplicate `baseline_rir`, and independent `rir_cue` |
| `scheduled_time` / `slot` | valid time from `scheduled_time`, else valid time from `slot`, else `NULL` | `scheduled_time` |
| cardio/comment/options | legacy truthiness; optional/recovery default false | `is_cardio`, `comment`, `optional`, `recovery_focused` |
| `details` | `Json` only when non-`None` | `details` |
| numeric targets | passed through for psycopg/PostgreSQL adaptation | `percent_1rm`, `target_weight_kg` |

Mapper-only `id`, exercise name, workout type, intensity, and muscle group remain
outside the writer's consumed shape. Mapper characterization separately pins
scheduled-time precedence, RIR precedence, metadata/details, optional/recovery,
difficulty, test-week, cardio, and comment-only behavior.

### Typed normal form and atomic writer

`infrastructure.plan_persistence` owns frozen plan/week/workout write facts, pure
normalization helpers, and a writer that receives an explicit cursor. The writer
acquires no pool, commits nothing, runs no migration or schema assurance, and
imports no application, CLI, or API code. `PostgresDal.save_full_plan` remains
the public compatibility and transaction facade: normalize, acquire one
connection/cursor, disable autocommit, write, commit, log, and return; every
writer or commit exception is rolled back and re-raised.

The normal SQL sequence is now DML-only: deactivate the old active plan, insert
the new active plan, insert its ordered weeks, and insert each ordered workout.
The partial unique index continues to enforce one active plan and is verified by
the migration/readiness schema gate. `PlanRepository` remains domain-owned and
infrastructure-free, with its existing dictionary-in/integer-ID-out signature.

### Characterization and feedback ratchets

The focused unit suite covers outer and nested validation, fallback/default
branches, generator and ordering behavior, all consumed columns, missing IDs,
JSON/SQL/cursor/commit errors, rollback, logging, the mapper/service boundary,
and DML-only statement inspection. The normalization/writer module has 100%
combined statement/branch coverage and zero strict-mypy errors together with the
existing repository port. Formatting checks pass for the six new/minimally
changed Python files; the read-only repository-wide baseline still reports 231
legacy files that would be reformatted, including `postgres_dal.py`.

Guarded PostgreSQL 15 tests verify complete values in all three tables, JSONB,
raw week and workout ordering, null exercise IDs, baseline/effective equality,
sequential activation, and rollback after plan insert, injected week insert,
workout FK/check/JSON adaptation, and deferred commit failures. A role with only
schema usage, plan-table DML, and plan-sequence privileges successfully saves on
the already migrated schema and has no schema `CREATE` privilege.

| Measure | Before | After |
| --- | ---: | ---: |
| `save_full_plan` physical span / complexity | 152 / 24 | 16 / 2 |
| DAL C901 findings / maximum | 3 / 24 | 2 / 16 |
| New helper maximum complexity | n/a | 5 |
| `postgres_dal.py` physical lines | 2,355 | 2,220 |
| DAL unit/contract branch-aware coverage | 34% displayed | 38.583411% |
| DAL combined unit/contract/PostgreSQL coverage | not measured | 40.913327% |
| Typed plan-persistence branch-aware coverage | n/a | 100% (120 statements, 36 branches) |
| Repository unit/contract branch-aware coverage | 69% displayed | 69.550367% (70% displayed) |
| Unit/contract lane | 838 passed, 7 skipped | 883 passed, 7 skipped |
| PostgreSQL schema/application lanes | no plan-save cases | 10 + 25 passed |
| Strict local legacy-DAL probe | 30 errors | 29 errors |
| Strict errors in repository port/new boundary | no declared scope | 0 |

Plan reads, the two unused legacy writers, readiness/difficulty methods, pool
ownership, strength-test persistence, Wger, nutrition, profiles, jobs, and all
other DAL families remain explicitly deferred.
