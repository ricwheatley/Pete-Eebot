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
origins, and the dependency import guard.

### Disposable PostgreSQL integration

The schema bootstrap drops and recreates objects. Start a dedicated disposable
database; never point this lane at the normal Compose database, a developer
database, or production.

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

After the guard passes, the fixture applies `init-db/schema.sql` and every
tracked migration. DAL tests use a real psycopg connection inside a forced
rollback transaction and verify that test rows are absent afterward.

### Installed artifact

```bash
python -m pytest -q -m artifact
```

This lane copies the current package sources to a clean temporary build tree,
builds a wheel, creates a clean virtualenv outside the checkout, installs the
runtime graph from `uv.lock`, and installs the wheel with dependency resolution
disabled. It then smokes `pete --help`, `pete status --help`, a side-effect-free
command, bundled templates/resources, API lifespan startup, and OpenAPI
generation. It also asserts that the installed package did not resolve from the
editable source checkout.

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
