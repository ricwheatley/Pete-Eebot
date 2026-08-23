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

### Future tranche order

Do not combine these into one change:

1. Characterize and split `infrastructure/apple_parser.py::parse` (complexity
   60, 60% module coverage) into record-recognition and mapping stages.
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

Residual risk remains in the untyped legacy payload entering the stable wrapper,
the low-covered DAL/CLI hotspots, and the repository's other 38 C901 findings.
The 66% repository floor is intentionally only a first ratchet and should rise
when a later tranche measurably improves the full baseline.
