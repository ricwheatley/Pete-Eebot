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

1. Treat `AppleHealthDropboxIngestor._run_ingest` and its discovery, transaction,
   checkpoint, equal-timestamp, retry, alert, and partial-file policies as a
   separate future coordinator tranche; none of it moved with parser decisions.
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
