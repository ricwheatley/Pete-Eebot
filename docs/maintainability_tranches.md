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

## 2026-08-27: verified GitHub push and replay-safe deploy dispatch

### Baseline and selected boundary

The tranche started from a clean `main` worktree at
`69ff9f50824960ba5788306931574f2a7cfece47`, aligned with `origin/main`; the
repository had advanced six commits beyond the supplied `b2faec2` measurement.
`api_routes/logs_webhooks.py` still had 246 physical lines and one C901 finding:
the 155-line `github_webhook` handler had complexity 20. The file imported three
project modules, and a strict isolated adapter probe reported the four known
FastAPI-decorator/return-annotation errors. The configured seven-file strict
scope remained clean.

The handler coupled exact-body HMAC authentication, JSON and push-policy trust,
job allocation, replay-ledger ownership, rate limiting, audit, correlation,
durable dispatch, ledger transitions, timestamping, and HTTP serialization. The
security risk was temporal rather than algorithmic: moving claim after rate,
auditing before a failed mark, or treating any 409 as ignored would change replay
or deployment behavior.

### Ordered delivery contract

Pre-extraction real-ASGI characterization pinned the coordinator order:

| State | Required order and outcome |
| --- | --- |
| Unauthenticated or malformed body | signature shape, bounded raw body, secret/HMAC, then authentication state; no signed-body decoding or trust filtering before valid HMAC |
| Invalid signed push/configuration | delivery ID, UTF-8/JSON/object, configuration, then event/repository/ref/deleted/commit policy; no job, claim, rate, audit, or dispatch |
| Accepted claim | allocate job, claim ledger, rate check, started audit, correlation/command/dispatch |
| Replayed claim | claim, succeeded audit, exact stored job/status response; no rate or dispatch |
| Rate failure | claim, rate, failed mark with 1,000-character reason, re-raise; no audit or dispatch |
| Ignored conflict | started audit, dispatch HTTP 409 with dictionary code `operation_in_progress`, timestamp, ignored mark, succeeded audit |
| Other HTTP/general failure | failed mark, exact failed audit at `ERROR`, then re-raise; collaborator failures replace the earlier error at the same legacy point |
| Success | dispatch, dispatched mark, UTC-Z timestamp, succeeded audit, response |

`application.github_deploy_webhook` now owns the frozen verified push, typed
verification failures, application-owned delivery claim/ledger protocol, explicit
replayed/ignored/dispatched outcomes, and coordinator. Verification is pure over
explicit header/body/secret/config inputs. The coordinator receives ledger,
rate, dispatch, audit, and clock ports and imports no FastAPI, Starlette,
PostgreSQL, API route, CLI, configuration, or composition module.

The FastAPI adapter retains exact streaming/body bounds, header extraction,
authentication state, request-based rate checks, correlation metadata, job
service dispatch, and HTTP/error serialization. Dependency composition exposes a
narrow `GitHubDeliveryLedger` while continuing to return the existing
`PostgresEdgeSecurityRepository`; the repository imports and returns the
application-owned `DeliveryClaim`. No migration, transaction, worker, command,
rate-limit, or trust-policy rule changed.

### Characterization and feedback ratchets

Seventy-two genuine TestClient cases cover signature shape and HMAC ordering,
explicit and chunked content lengths at/over the boundary, UTF-8/JSON/object
failures, configuration conversion, all push-policy branches, delivery-ID
boundaries, every stored replay state, rate failure/truncation, exact dispatch
metadata, the sole ignored conflict, other HTTP/general failures, and mark/audit/
correlation/command/clock propagation points. Fifty direct unit cases give the
pure verifier/coordinator 100% combined statement/branch coverage. Existing
concurrent TestClient replay tests continue to prove one dispatch and original
job reuse for both same-delivery and altered-delivery replays.

One legacy configuration ambiguity is deliberately unchanged: a non-numeric
repository ID raises `ValueError` and is serialized as the generic 500 envelope,
whereas missing or non-positive values receive the documented 503 response.

Guarded PostgreSQL 15 tests add dispatched/ignored/failed mark visibility and a
real-ASGI handler-to-real-ledger accepted/replay path with an owned fake external
dispatcher. The existing concurrent two-repository claim test still proves one
accepted winner and one job ID. Schema and job-ownership lanes passed before the
disposable container was removed.

The pre-extraction 36% route coverage was an instrumentation defect, not an ASGI
execution gap. Coverage 7.15.4 recorded `github_webhook` through its first body
await and then emitted the function-exit arc even while `sys.gettrace()` and the
live caller frame both held the same C tracer and the request completed with
ledger/dispatch side effects. Canonical source paths ruled out aliasing;
`--concurrency=thread` was unchanged, and the Python `--timid` tracer failed
inside coverage's async stack tracking. This matches open coverage.py issue
[#2245](https://github.com/coveragepy/coveragepy/issues/2245). Extraction makes all
security decisions independently creditable and raises the route report to 85%;
the remaining uncredited webhook lines are exactly 251-256 after the same await.
The repository floor remains 66%.

| Measure | Before | After |
| --- | ---: | ---: |
| `github_webhook` physical span / complexity | 155 / 20 | 9 / 2 |
| Adapter/new-boundary maximum complexity | 20 | 7 / 4 |
| `logs_webhooks.py` physical lines / statements | 246 / 139 | 256 / 120 |
| Route project-module imports | 3 | 4 (one explicit application boundary) |
| Pure boundary framework/project imports | n/a | 0 |
| `logs_webhooks.py` branch-aware coverage | 36% | 85% |
| Verifier/coordinator branch-aware coverage | n/a | 100% (194 statements, 28 branches) |
| Combined route/boundary branch-aware coverage | n/a | 94% |
| Repository unit/contract branch-aware coverage | 69.550367% | 70.203819% |
| Unit/contract lane | 883 passed, 7 skipped | 1,005 passed, 7 skipped |
| Guarded PostgreSQL schema / edge / job lanes | existing controls | 10 / 7 / 5 passed |
| Configured strict mypy scope | 0 errors in 7 files | 0 errors in 8 files |
| Isolated adapter errors | 4 | 3 (remaining FastAPI decorators plus out-of-scope GET return) |

GET `/logs`, deployment worker/ownership, rate-limit policy, edge-security schema,
other API and web-console routes, plan persistence, Apple ingestion, narrative,
CLI behavior, and all unrelated families remain explicitly deferred.

## 2026-08-27: typed body-age history and trend analysis

### Baseline and selected boundary

The tranche started from a clean `main` worktree at
`6f60ce626411e28ba04db6e87c3598c57de97136`, aligned with `origin/main`. The
repository had advanced beyond the supplied `b2faec2` measurement. On the
current commit, `body_age.py` remained 413 physical / 334 nonblank,
non-comment lines. `get_body_age_trend` was a 69-line, complexity-20 function;
`calculate_body_age` remained a 203-line, complexity-24 function. The module's
unit/contract branch-aware coverage was 66.451613%, and the repository measured
70.203819% with 1,005 passing tests and 7 skips. The isolated strict probe
reported six errors.

The trend function mixed two optional DAL capabilities, exception and iterable
compatibility, arbitrary persistence shapes, conversion, window filtering,
stable duplicate ordering, latest-point selection, exact-date comparison, and
rounding. It was selected as a bounded read-side seam with two production
summary consumers. The exploratory Python calculator and authoritative
PostgreSQL `sp_upsert_body_age` calculation were explicitly excluded.

### Typed history port and pure decision boundary

`domain.body_age_history` now owns `BodyAgeHistoryRow`, the structural
`BodyAgeHistoryReader` protocol, and `LegacyBodyAgeHistoryReader`. The adapter
preserves range-method preference, the eight-row fallback only when the range
method is unavailable, broad synchronous loader-error suppression, eager
materialization of non-list iterables, and propagated iteration/materialization
errors.

`domain.body_age_trend.analyze_body_age_trend` owns conversion, the inclusive
eight-date window, stable ordering, latest-point selection, exact
`target_date - 7 days` comparison, duplicate behavior, and one-decimal output.
It imports only the domain-owned row type; neither new module imports
application, infrastructure, CLI, API, framework, or PostgreSQL code. The
compatibility facade keeps the existing `get_body_age_trend(dal,
target_date=None)` interface and re-exports `BodyAgeTrend` from
`domain.body_age`.

Fifty-six new tests cover the pure boundary, adapter/facade characterization,
and both summary consumers. Characterization pins missing/non-callable/both
capabilities, synchronous versus iterator errors, `None`/list/tuple/generator
and malformed results, the default clock, flat/nested/falsey values, converter
quirks, every accepted and invalid date form, window edges, unordered and
duplicate dates, exact versus nearby comparisons, and positive/negative
rounding behavior.

| Measure | Before | After |
| --- | ---: | ---: |
| `get_body_age_trend` physical span / complexity | 69 / 20 | 12 / 3 |
| `body_age.py` physical / nonblank non-comment lines | 413 / 334 | 353 / 283 |
| New helper maximum complexity | n/a | 8 |
| Repository C901 findings | 36 | 35 |
| Legacy module branch-aware coverage | 66.451613% | 70.044053% |
| New history/analyzer branch-aware coverage | n/a | 100% (116 statements, 40 branches) |
| Combined body-age module/boundary coverage | 66.451613% | 82% displayed |
| Repository unit/contract branch-aware coverage | 70.203819% | 70.536402% (71% displayed) |
| Unit/contract lane | 1,005 passed, 7 skipped | 1,061 passed, 7 skipped |
| Configured strict mypy scope | 0 errors in 8 files | 0 errors in 10 files |
| Isolated legacy-module strict errors | 6 | 5, all in deferred calculator support/calculation code |

`calculate_body_age` is byte-for-byte unchanged at the function-source level,
and no DAL query, migration, SQL scoring rule, schema, ingestion path, CLI or
Telegram wording, or daily-summary formatting policy changed. Calculator
parity, daily-summary consolidation, and the remaining trend/data-shape quirks
remain separate decisions.

## 2026-08-27: typed weekly workout presentation

### Baseline and selected boundary

The tranche started from a clean `main` worktree at
`fedd90c3ff7d1ccaceb20d6021c233331dee66d6`, aligned with `origin/main`.
`narrative_builder.py` had 1,405 physical lines and three C901 findings.
`_format_weekly_workouts` spanned 54 lines at complexity 14, while the 32-line,
complexity-8 `build_weekly_plan_summary` parsed the helper's `"- Day: a | b"`
strings back into days and sessions. The unit/contract lane passed 1,061 tests
with 7 skips at 70.536402% branch-aware repository coverage. The isolated
strict legacy-module probe reported 10 errors.

Characterization pinned the raw-row mapping before extraction:

| Raw branch or field | Name/details behavior | Ordering behavior |
| --- | --- | --- |
| `day_of_week` | `int` coercion; missing, invalid, and values outside 1-7 are omitted | Days render Monday through Sunday |
| mapping `details` | `comment`, then `exercise_name`, then `Run`; an empty mapping still selects this naming branch | Existing `workout_display_order` receives the mapping |
| non-mapping `details` | `exercise_name`, then `Exercise {exercise_id}` | Existing policy receives `details=None` |
| recognized treadmill steps | Exact interval, tempo, easy, steady, recovery, and long-run instructions | Run session types precede strength |
| stretch routine steps | Display-name fallback; malformed steps skipped; isometric/dynamic/hold wording retained | Stretch/mobility follows strength |
| `sets` and `reps` | Render together only when both are non-`None` and no instruction rendered | Does not affect ordering |
| `target_weight_kg` / `weight_kg` | Truthy target wins; a zero target falls back to current weight; shown only for falsey `details` payloads | Does not affect ordering |
| `rir` / `optional` | RIR is shown only for falsey `details`; any truthy optional value adds the marker | Does not affect ordering |
| order ties | Session text is otherwise unchanged | Original input position is the stable tie-breaker |

### Typed boundary and compatibility

`domain.weekly_plan_presentation` now owns frozen session, day, and complete
seven-day presentation values. Separate functions normalize one row, render
treadmill/stretch instructions, group and stably order sessions, and perform
final text layout. The ordering callable and stretch session identifier are
explicit inputs; the module imports only the standard library and has no CLI,
application, infrastructure, framework, phrase, or mutable-global dependency.

The public raw-list facade and both compatibility facades are unchanged. The
public path is now raw rows -> typed sessions/days -> final text. It never
creates or reparses day bullet strings. `_format_weekly_workouts` remains a
private compatibility adapter over the typed model. A named final-layout rule
deliberately preserves the old defect where `|` inside a session name/comment
creates another output line; `: ` remains ordinary text. Non-empty
`week_start` remains ignored. Empty days remain available as typed rest
metadata, while public output still discards them.

### Characterization and feedback ratchets

Twenty-six facade/real-Typer characterizations and 17 direct pure tests cover
empty and all-seven-day layouts, invalid/coerced days, stable ties, structured
and legacy naming, zero/falsey/detail precedence, every treadmill family,
short/malformed nested steps, stretch styles and malformed steps, duplicate and
delimiter sessions, ignored `week_start`, computed rest days, generators,
non-mapping row errors, exact whitespace, print/send output, and Telegram send
failure. The exact characterizations passed both before and after extraction.
Related schedule/export and plan-mapper tests also remained green.

CI additively includes the pure module in strict mypy, enforces its 100%
statement/branch coverage, and format-checks only the weekly tranche files in
addition to the prior ratchet. The repository floor remains 66%.

| Measure | Before | After |
| --- | ---: | ---: |
| `_format_weekly_workouts` physical span / complexity | 54 / 14 | 3 / 1 |
| `build_weekly_plan_summary` physical span / complexity | 32 / 8 | 14 / 2 |
| Narrative-builder C901 findings | 3 | 2 |
| Repository C901 findings | 35 | 34 |
| New helper maximum complexity | n/a | 5 |
| `narrative_builder.py` physical lines | 1,405 | 1,253 |
| New presentation branch-aware coverage | n/a | 100% (197 statements, 66 branches) |
| Combined narrative/presentation coverage | 70% legacy module | 75.845791% |
| Repository unit/contract branch-aware coverage | 70.536402% | 70.846850% |
| Unit/contract lane | 1,061 passed, 7 skipped | 1,104 passed, 7 skipped |
| Configured strict mypy scope | 0 errors in 10 files | 0 errors in 11 files |
| Isolated legacy-module strict probe | 10 errors | 9 errors when the new typed module is explicit |

CLI weekly-plan selection, voice composition and delivery orchestration, plan
generation/persistence/mappers, schedule policy, weekly metric analysis, trend
analysis, and every daily/cycle narrative remain explicitly deferred.

## 2026-08-27: typed Steps/Sleep metric trends

### Baseline and selected boundary

The tranche started from a clean `main` worktree at
`d3675ea320586802df0ce2b067c0bf779cb2ed1e`, aligned with `origin/main`. This
was seven commits beyond the supplied `b2faec2` measurement and already
included the completed weekly workout presentation boundary.
`narrative_builder.py` measured 1,253 physical / 1,002 token-bearing lines and
had two C901 findings: the 37-line, complexity-11 `compute_trend_lines` and the
deferred complexity-12 daily-from-days builder. The trend helper maximum was 9,
and the repository had 34 C901 findings. The unit/contract lane passed 1,104
tests with 7 skips at 70.846850% branch-aware repository coverage; the legacy
narrative module displayed 70% coverage. An isolated strict probe reported no
local narrative-builder errors and 19 followed-import errors, while the
configured 11-file strict scope was clean.

The trend path coupled accepted-row recognition, date and numeric conversion,
raw dictionary precedence, three windows, duplicate sample counting, minimums,
significance decisions, formatting, and final prose. It was selected because
the weekly narrative, CLI summary, and application Orchestrator all depend on
its exact two-line result, while the calculation itself is a bounded pure
Steps/Sleep policy.

### Preserved metric and window policy

| Metric | Raw paths in precedence order | Eligible value | Value / delta format | Current significance |
| --- | --- | --- | --- | ---: |
| Steps | `activity.steps`, then `steps` | first convertible value greater than zero | comma-grouped zero-decimal `steps/day` / `steps` | 400 steps |
| Sleep | `sleep.asleep_minutes`, then `sleep_asleep_minutes` | first convertible value greater than zero | minutes converted to one-decimal `h/night` / `h` | 6 minutes |

Both metrics retain minimums of 4 samples in the inclusive target-6 through
target week, 20 samples in target-29 through target month, and 21 samples in
the target-89 through target-30 baseline. Duplicate-day rows remain separate
samples and remain described as logged "days." Current significance is
inclusive at the metric threshold; baseline significance is inclusive at half
that threshold. Steps always render before Sleep. The latest accepted row still
sets the default target date, explicit targets still exclude future values, and
`limit` still applies as a Python slice only after both lines are rendered and
sentence-normalized.

### Typed boundary and compatibility facade

`domain.metric_trends` now owns frozen metric definitions, normalized
Steps/Sleep samples, per-window count/mean statistics, typed availability,
direction and baseline states, policy decisions, and exact rendering. Date
parsing and sentence normalization are explicit collaborators supplied by the
legacy facade, preserving `converters.to_date` and `formatters.ensure_sentence`
without creating a project dependency in the pure module. The module has no
project, application, CLI, API, infrastructure, framework, filesystem, or
mutable-global import, so the dependency remains acyclic.

`narrative_builder.compute_trend_lines` keeps its existing signature and is a
13-line compatibility delegate. The weekly analyzer still receives that facade
as its trend collaborator. The CLI and Orchestrator retain their independent
sample loaders and paragraph ownership; none of the three consumers changed.

### Characterization and feedback ratchets

Sixty-two facade characterizations passed against the original implementation
before extraction and after delegation; the final facade suite has 72 cases
after adding symmetric negative-threshold and non-finite conversion cases. They cover empty/all-invalid rows,
non-mappings, invalid and converted dates, datetimes, ordering, duplicates,
future rows, default/explicit targets, every window edge, both schema paths and
fallback precedence, numeric strings, zero/negative/invalid values, sample
counts immediately below/at/above 4, 20, and 21, current thresholds immediately
below/at/above 400 and 6 in both directions, baseline half-thresholds and every
state, exact rounding/punctuation, sentence normalization, and `None`, zero,
positive, oversized, and negative limits. Forty-five direct pure cases assert
normalized facts, statistics, typed decisions, rendering, invalid fallbacks,
and immutability independently. Three compatibility tests exercise exact output
through the weekly narrative, CLI summary, and application Orchestrator.

CI additively includes the pure module in strict mypy, gives it a 100%
statement/branch coverage ratchet, and format-checks only the four new source/
test files. The legacy narrative-builder formatting backlog remains untouched.
The repository coverage floor remains 66%.

| Measure | Before | After |
| --- | ---: | ---: |
| `compute_trend_lines` physical span / complexity | 37 / 11 | 13 / 2 |
| Narrative-builder C901 findings | 2 | 1 (deferred daily-from-days only) |
| Repository C901 findings | 34 | 33 |
| New helper maximum complexity | n/a | 5 |
| `narrative_builder.py` physical / token-bearing lines | 1,253 / 1,002 | 1,071 / 853 |
| Typed boundary physical / token-bearing lines | n/a | 456 / 364 |
| Typed boundary branch-aware coverage | n/a | 100% (219 statements, 66 branches) |
| Narrative builder / typed boundary combined coverage | 70% legacy module | 75.746606% |
| Repository unit/contract branch-aware coverage | 70.846850% | 71.132837% |
| Unit/contract lane | 1,104 passed, 7 skipped | 1,224 passed, 7 skipped |
| Configured strict mypy scope | 0 errors in 11 files | 0 errors in 12 files |
| Isolated new-boundary strict errors | n/a | 0 |

The statistical oddities are deliberately unchanged: duplicate rows inflate
sample counts, the 30-day comparison contains the 7-day window, sparse fallback
can report all older filtered samples when the current month is empty, and
non-finite float inputs retain Python's existing arithmetic/formatting behavior.
Changing those product rules requires a separate decision. Daily-summary
paragraph consolidation, body-age trends, weekly metric/workout analysis,
daily-from-days narrative construction, body age calculation, cycle narrative,
Apple ingestion, PostgreSQL/DAL work, CLI commands, and Orchestrator behavior
remain explicitly deferred.

## 2026-08-28: application-owned daily-summary construction

### Baseline and selected boundary

This tranche started from a clean `main` worktree at
`3510e12b6977da0fd73f4204b0b1b45c38b953b4`, aligned with `origin/main`.
That commit included the completed typed Body Age history/trend and Steps/Sleep
metric-trend prerequisites. The current baseline was remeasured rather than
reusing the older supplied `b2faec2` measurements: `messenger.py` was 1,699
physical / 1,446 token-bearing lines and `orchestrator.py` was 1,418 / 1,240.
The CLI and Orchestrator each owned complexity-11 body-composition trees plus
complexity-17 and complexity-15 HRV trees. The repository had 33 C901 findings.

An AST graph over every `pete_e/**/*.py` file expanded project imports and
constant `importlib.import_module` calls, then applied Tarjan's algorithm. It
found one six-module summary component containing Orchestrator, application
sync, the Telegram listener, `DailySyncWorkflow`, `cli.messenger`, and
`cli.telegram`. `DailySyncWorkflow` imported the CLI summary builder inside
`run`, while the listener held a lazy CLI-module proxy. The repository had two
statically visible application-to-CLI edges, including the summary workflow
edge; the other (`application.api_services` to `cli.status`) is unrelated.
Messenger's project fan-out was 24 under this current graph method.

The pre-edit unit/contract lane passed 1,224 tests with 7 skips at 71.135291%
combined statement/branch coverage. Messenger, Orchestrator,
`DailySyncWorkflow`, and the Telegram listener measured 49.283154%,
63.927428%, 88.372093%, and 72.180451%, respectively. The configured strict
mypy scope was clean in 12 files; isolated non-gating strict probes of the two
legacy facades reported 50 messenger and 17 Orchestrator errors.

### Typed construction and compatibility policies

`application.daily_summary` now owns the `DailySummaryMessageBuilder` protocol,
the supplemental history-loading service, immutable body-composition and HRV
analysis results, pure analyzers, and explicit `PRODUCTION` and `LEGACY_CLI`
render profiles. It consumes the completed `BodyAgeHistoryReader`/
`analyze_body_age_trend` and `metric_trends.compute_trend_lines` boundaries.
Loading, analysis, and rendering remain separate. The maximum complexity of a
new function is 5.

Orchestrator remains the authoritative production builder and retains its
draft, structured `CoachVoiceRequest`, composer-versus-rewrite selection,
fallback, target/action dates, training guidance, nutrition, logging, and
application error semantics. Its supplemental methods are compatibility
delegates to the production profile. `CompatibleDailySummaryMessageBuilder`
preserves the public messenger wrapper's callable-authoritative delegation and
duck-typed `get_daily_summary`/DAL fallback. `DailySyncWorkflow` receives the
protocol explicitly. The Telegram listener also receives it explicitly and
falls back to the same Orchestrator instance when composed without one. CLI is
limited to presentation, transport, and legacy-profile adaptation.

Characterization against identical 90-day data pinned the intentional prose
differences instead of harmonizing them:

| Case | Production profile | Legacy CLI profile |
| --- | --- | --- |
| Missing Body Age value | omit the line | `Body Age: n/a` |
| HRV rise, 75 vs 70 ms | `HRV: 75 ms (up) vs 7d avg 70 ms` | `HRV: 75 ms ↗ (7d avg 70 ms)` |
| Numeric strings | preserve the production Decimal-only behavior | accept through `float` |
| Body-composition `None`/non-dict rows | defensive empty/skip behavior | retain observed `TypeError`/`AttributeError` |

Both profiles retain Body Age delta wording, muscle windows/minimums/rounding
and the +/-0.5 threshold, HRV key precedence/positive filtering/seven-day
selection/rounding and the +/-2 threshold, Steps-before-Sleep ordering, warning
text and levels, default-yesterday behavior, and newline appending. The
date-before-datetime compatibility branch remains intentionally shadowed.

### Tests and feedback ratchets

The final focused suite has 133 cases covering pure analysis and rendering,
production-versus-legacy snapshots, malformed history and loader errors,
Orchestrator voice/fallback/error contracts, workflow injection and send
outcomes, Telegram `/summary`, dependency direction, and genuine Typer/Click
`message --summary` and `morning-report` parsing, output, sends, failures, and
exit codes. The unit/contract lane now passes 1,326 tests with 7 skips. No
PostgreSQL query changed, so no database integration was added.

CI additively strict-checks the application module, enforces 100% combined
statement/branch coverage for its 329 statements and 120 branches, and
format-checks only the seven new source/test files. Repository-wide Ruff still
passes and the coverage floor remains 66%.

| Measure | Before | After |
| --- | ---: | ---: |
| Targeted duplicate body-composition/HRV decision trees | 4 | 0 (thin public/private delegates retained) |
| Messenger / Orchestrator C901 findings | 7 / 3 | 5 / 1, all unrelated to daily-summary enrichment |
| Repository C901 findings | 33 | 29 |
| New helper maximum complexity | n/a | 5 |
| `messenger.py` physical / token-bearing lines | 1,699 / 1,446 | 1,557 / 1,319 |
| `orchestrator.py` physical / token-bearing lines | 1,418 / 1,240 | 1,291 / 1,116 |
| New application boundary physical / token-bearing lines | n/a | 646 / 535 |
| Messenger project fan-out | 24 | 24 |
| Summary application-to-CLI edge | 1 | 0 |
| Summary SCC | 6 modules | none |
| New application boundary branch-aware coverage | n/a | 100% |
| Messenger branch-aware coverage | 49.283154% | 49.215247% |
| Orchestrator branch-aware coverage | 63.927428% | 73.233696% |
| Daily workflow / Telegram listener coverage | 88.372093% / 72.180451% | 100% / 80.991736% |
| Repository unit/contract branch-aware coverage | 71.135291% | 72.329850% |
| Unit/contract lane | 1,224 passed, 7 skipped | 1,326 passed, 7 skipped |
| Configured strict mypy scope | 0 errors in 12 files | 0 errors in 13 files |
| Isolated legacy messenger / Orchestrator strict probes | 50 / 17 | 57 / 22 (non-gating legacy backlog) |

The remaining nontrivial component contains only application composition,
infrastructure DI, and the Telegram notification channel. The unrelated
`application.api_services` to `cli.status` edge also remains. Web
morning-report and generic-message routes continue to use the compatibility CLI
facade and are deferred, as are trainer summaries and weekly-plan presentation.

## 2026-08-28: application-owned weekly-plan presentation

### Baseline and protected contract

This tranche started from a clean `main` worktree at
`c9e1e452ef13d59f17cdd4a1f8f51668353b6fff`, aligned with `origin/main`.
The completed typed workout renderer and atomic plan-write tranches were
verified first; neither was expanded. `messenger.py` measured 1,557 physical /
1,319 token-bearing lines. `build_weekly_plan_overview` still spanned 95 lines
at complexity 19, the CLI had five C901 findings, and its documented
unit/contract branch-aware coverage was 49.215247%. The configured strict scope
was clean in 13 files.

Pre-extraction characterizations pinned all plan-source capability combinations,
`get_plan_week` preference, lifecycle/date/duration/identifier boundaries,
falsey and generator row behavior, renderer failure behavior, exact error/log
text, structured coach state and trusted `local-cli` principal, every voice
request field, required-term uniqueness/cap, composer quirks, and genuine
Typer print/send/empty/error/multi-flag behavior. They also retain the surprising
generator rule: rendering may consume a one-shot iterable before voice context
is materialized.

### Typed reader and presentation boundary

`application.weekly_plan_message` now owns the structural `WeeklyPlanReader`,
renderer, coach-state, voice-composer, logger, and message-builder ports plus the
date/week lifecycle and exact voice-request construction. The compatibility
reader adapter performs legacy capability discovery once and preserves
`get_plan_week` preference over `get_plan_week_rows`. The decision service has no
CLI, concrete DAL, PostgreSQL, Typer, FastAPI, or infrastructure import, and no
dynamic collaborator discovery.

`application.weekly_plan_context` supplies the established `MetricsService`
coach state under the same trusted CLI principal and adapts legacy duck-typed
orchestrators at composition time. Orchestrator exposes and accepts the message
builder port. The CLI wrapper now selects that port, supplies its local clock,
and returns the message; `message --plan` retains only heading, terminal output,
empty guarding, logging, and Telegram delivery.

Coach voice request values moved unchanged into the framework-free
`application.coach_voice_types` module so the new application boundary can join
the additive strict-mypy scope without pulling the legacy logging/configuration
graph into that gate. `application.coach_voice` continues to re-export the same
classes and its service behavior is unchanged.

### Characterization and feedback ratchets

The focused application/domain/voice/Typer suite passes 130 tests. The complete
unit/contract lane passes 1,386 tests with 7 skips, and repository branch-aware
coverage is 72.739558%. The three new typed request/context/decision modules have
100% combined statement/branch coverage. CI additively enforces that result,
strict-checks the request values and decision service, and format-checks only the
new tranche files. No PostgreSQL adapter changed, so guarded database integration
was not run.

| Measure | Before | After |
| --- | ---: | ---: |
| `build_weekly_plan_overview` physical span / complexity | 95 / 19 | 11 / 1 |
| Messenger C901 findings | 5 | 4 (all unrelated to weekly-plan selection) |
| Repository C901 findings | 29 | 28 |
| New decision helper maximum complexity | n/a | 6 |
| `messenger.py` physical / token-bearing lines | 1,557 / 1,319 | 1,376 / 1,159 |
| New typed request/context/decision modules physical / token-bearing lines | n/a | 629 / 521 |
| Messenger direct project-module fan-out | 21 | 21 |
| New decision-service adapter/framework imports | n/a | 0 |
| New typed boundary branch-aware coverage | n/a | 100% (265 statements, 78 branches) |
| Messenger branch-aware coverage | 49.215247% | 46.174142% after covered decisions moved out |
| Repository unit/contract branch-aware coverage | 72.329850% | 72.739558% |
| Unit/contract lane | 1,326 passed, 7 skipped | 1,386 passed, 7 skipped |
| Configured strict mypy scope | 0 errors in 13 files | 0 errors in 15 files |

The domain weekly workout renderer, schedule policy, plan reads and writes,
generation, schema, migrations, Telegram provider, authentication policy, daily
and trainer summaries, Telegram listener, web generic-message migration, and all
other CLI families remain explicitly deferred.
