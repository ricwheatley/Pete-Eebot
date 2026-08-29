# Testing with real dependencies

Pete-Eebot's tests always import the installed FastAPI, Starlette, Pydantic,
Pydantic Settings, Typer, Click, Tenacity, requests, Dropbox, psycopg, and Rich
packages. `tests/conftest.py` isolates settings from the repository `.env` and
supplies non-production defaults, but it does not manufacture dependency
modules.

## Install the locked dependency set

`pyproject.toml` is the only hand-edited dependency input. CI uses its declared
Python matrix and uv 0.12.5 to install the exact development graph from
`uv.lock`:

```bash
uv lock --check
uv sync --frozen --no-editable
.venv/bin/python -m pip check
.venv/bin/python -m pip_audit --local --skip-editable
```

Python 3.11 through 3.13 are supported by project metadata. CI runs the unit and
contract lanes on 3.11 and 3.13; production and the PostgreSQL/artifact jobs use
3.11. The universal lock preserves Python and OS markers across that range.

Pytest uses strict marker validation. Tests without an explicit external lane
marker are classified as `unit` during collection.

## Lanes

### Unit

```bash
python -m pytest -q -m unit
```

This is the fast domain/application lane. Network providers, clocks,
repositories, pools, and similar boundaries may be replaced only at local,
application-owned ports. Installed third-party packages are still imported.

### Real-framework contracts

```bash
python -m pytest -q -m contract
```

This lane covers real ASGI request parsing and response serialization, FastAPI
validation, Typer/Click parsing and help rendering, Pydantic Settings loading
from temporary env files, real Tenacity retries with zero delay, psycopg import
origins, and the dependency import guard. Morning-report browser operations are
covered through the installed FastAPI/Starlette stack in
`tests/test_morning_report_fastapi_contract.py`, including sessions, cookies,
CSRF, RBAC, validation, middleware, job callbacks, audit, IDs, and error
serialization.

### Disposable PostgreSQL integration

The fixture invokes the guarded development reset and authoritative runner. Start
a dedicated disposable database; never point this lane at the normal Compose
database, a developer database, or production.

```bash
docker run --rm --name pete-e-test-postgres \
  -e POSTGRES_DB=pete_e_test_local \
  -e POSTGRES_USER=pete_test \
  -e POSTGRES_PASSWORD=pete_test \
  -p 127.0.0.1:55432:5432 \
  -d postgres:15

export PETEEEBOT_TEST_DATABASE_URL=postgresql://pete_test:pete_test@127.0.0.1:55432/pete_e_test_local
python -m pytest -q -m integration --run-postgres
docker stop pete-e-test-postgres
```

The lane refuses to start unless all of these are true:

- `--run-postgres` was passed;
- `PETEEEBOT_TEST_DATABASE_URL` was set explicitly;
- the database name starts with `pete_e_test`;
- the database user contains `test`;
- the host is loopback-only.

After the guard passes, the fixture resets `public` and upgrades empty-to-head.
The schema-management integration file runs first in CI and covers
previous-release upgrade with retained data, linear baseline adoption, retired
reset-snapshot adoption, failed migration rollback/rerun, no-op-at-head,
readiness, repository smokes, and the guarded reset. Unit tests separately cover
manifest order and checksum drift. DAL tests use a real psycopg connection inside
a forced rollback transaction and verify that test rows are absent afterward.

### Installed artifact

```bash
python -m pytest -q -m artifact
```

This lane uses the pinned uv build tool to build both wheel and sdist from the
repository, including with local environments and generated metadata present.
It inspects both complete member lists and rejects tests, environments, scripts,
docs, logs, caches, deployment helpers, or unrelated namespaces. It requires the
allowlisted JSON, CSV, templates, static assets, and migrations.

It then creates a clean virtualenv outside the checkout, installs the runtime
graph from `uv.lock`, and installs the wheel with dependency resolution disabled.
From a non-repository working directory it smokes `pete --help`, `pete status
--help`, a side-effect-free command, actual phrase and cron loading, schema
migrations, API lifespan startup, and OpenAPI generation. It also asserts that
the installed package did not resolve from the source checkout.

## Wider validation

Run all non-database lanes together with:

```bash
python -m pytest -q -m "unit or contract"
python -m pytest -q -m artifact
```

Run the unfiltered suite only when the PostgreSQL opt-in is intentional; without
it, the integration test is skipped by design:

```bash
python -m pytest -q
```

## Maintainability feedback ratchets

The repository measures combined line and branch coverage for the real-framework
unit/contract lanes. The 66% floor is the measured non-regression baseline from
the first maintainability tranche; do not lower it to accommodate a change.

```bash
coverage erase
coverage run -m pytest -q -m "unit or contract"
coverage report
coverage report --fail-under=100 \
  pete_e/domain/body_age_history.py \
  pete_e/domain/body_age_trend.py
coverage report --fail-under=100 pete_e/domain/metric_trends.py
coverage report --fail-under=100 pete_e/domain/weekly_narrative.py
coverage report --fail-under=100 pete_e/domain/weekly_plan_presentation.py
coverage report --fail-under=100 pete_e/application/daily_summary.py
coverage report --fail-under=100 pete_e/application/morning_report.py
coverage report --fail-under=100 \
  pete_e/application/coach_voice_types.py \
  pete_e/application/weekly_plan_context.py \
  pete_e/application/weekly_plan_message.py
coverage report --fail-under=100 \
  pete_e/infrastructure/apple_parser.py \
  pete_e/infrastructure/apple_parser_normalization.py \
  pete_e/infrastructure/apple_parser_stages.py \
  pete_e/infrastructure/apple_parser_types.py
coverage report --fail-under=100 \
  pete_e/infrastructure/apple_ingest_coordinator.py
coverage report --fail-under=100 \
  pete_e/infrastructure/plan_persistence.py
```

Static typing covers explicit completed-tranche scopes and should expand one
boundary at a time rather than suppressing the existing repository backlog. The
current strict scope includes the typed body-age history reader and pure trend
analyzer, the Steps/Sleep metric-trend boundary, the weekly narrative module,
the typed weekly-plan presentation
boundary, the application-owned daily-summary construction boundary, the typed
morning-report build/send decision and result, the
framework-free coach-voice request values, the weekly-plan message decision
boundary, the three
pure Apple parser boundary modules, and the pure Apple
ingest outcome/checkpoint coordinator. It also covers the domain-owned plan
repository port and typed full-plan normalization/cursor-writer boundary:

```bash
mypy
```

Ruff's intended lint scope is repository-wide Python. Formatting remains a
staged ratchet because a full pass would currently mix hundreds of mechanical
changes with behavioral work:

```bash
ruff check pete_e tests scripts
ruff format --check \
  pete_e/domain/repositories.py \
  pete_e/domain/body_age_history.py \
  pete_e/domain/body_age_trend.py \
  pete_e/domain/metric_trends.py \
  pete_e/domain/weekly_narrative.py \
  pete_e/domain/weekly_plan_presentation.py \
  pete_e/application/coach_voice_types.py \
  pete_e/application/daily_summary.py \
  pete_e/application/morning_report.py \
  pete_e/application/weekly_plan_context.py \
  pete_e/application/weekly_plan_message.py \
  pete_e/infrastructure/apple_parser.py \
  pete_e/infrastructure/apple_parser_normalization.py \
  pete_e/infrastructure/apple_parser_stages.py \
  pete_e/infrastructure/apple_parser_types.py \
  pete_e/infrastructure/apple_health_ingestor.py \
  pete_e/infrastructure/apple_ingest_coordinator.py \
  pete_e/infrastructure/plan_persistence.py \
  tests/domain/test_body_age_trend_analysis.py \
  tests/domain/test_body_age_trend_characterization.py \
  tests/domain/test_metric_trends.py \
  tests/domain/test_metric_trend_characterization.py \
  tests/application/test_metric_trend_consumers.py \
  tests/application/test_body_age_trend_consumers.py \
  tests/application/test_daily_summary.py \
  tests/application/test_daily_summary_characterization.py \
  tests/application/test_daily_summary_dependencies.py \
  tests/application/test_daily_summary_orchestrator_contract.py \
  tests/application/test_daily_sync_workflow_characterization.py \
  tests/application/test_morning_report.py \
  tests/application/test_morning_report_composition.py \
  tests/application/test_morning_report_dependencies.py \
  tests/application/test_coach_voice_types.py \
  tests/application/test_weekly_plan_application.py \
  tests/application/test_weekly_plan_message_dependencies.py \
  tests/application/test_weekly_plan_orchestrator_contract.py \
  tests/cli/test_daily_summary_cli.py \
  tests/domain/test_weekly_narrative_analysis.py \
  tests/domain/test_weekly_narrative_characterization.py \
  tests/domain/test_weekly_plan_presentation.py \
  tests/test_apple_ingest_adapter_contract.py \
  tests/test_apple_ingest_coordinator.py \
  tests/test_apple_parser_characterization.py \
  tests/test_apple_parser_stages.py \
  tests/infrastructure/test_plan_persistence.py \
  tests/infrastructure/test_plan_save_mapper_contract.py \
  tests/integration/test_plan_persistence_integration.py \
  tests/test_plan_persistence_characterization.py \
  tests/test_weekly_plan_message.py \
  tests/test_weekly_plan_message_characterization.py \
  tests/test_morning_report_fastapi_contract.py
```

See [Incremental maintainability tranches](maintainability_tranches.md) for the
selected boundary, before/after measurements, and future tranche order.
