# API v1 Migration Note

Date: 2026-05-15

## Scope

Phase 1 introduces a versioned API namespace at `/api/v1` for the existing FastAPI route surface.

## What changed

- Every existing route module mounted by `pete_e/api.py` is now mounted twice:
  - legacy unversioned paths such as `/metrics_overview`
  - versioned paths such as `/api/v1/metrics_overview`
- The versioned routes call the same handlers as the legacy routes, so response shapes and auth behavior are intentionally unchanged in this phase.
- Key read-route wiring is covered by `tests/integration/test_api_contracts.py`.

## Client migration path

New clients, including the web UI, should use `/api/v1` immediately.

Existing clients may continue to call unversioned routes during the transition window. Those routes are retained only for backward compatibility and should be treated as deprecated from 2026-05-15.

## Deprecation path

1. Phase 1: keep legacy and `/api/v1` routes in parallel.
2. Phase 2: move browser-facing clients to `/api/v1` only while auth is tightened.
3. After all known automation and UI callers have migrated, announce a removal date for unversioned API routes.
4. Remove unversioned routes in a later hardening phase after a production deploy has run without legacy route traffic.

Until removal, bug fixes must preserve payload compatibility between legacy and `/api/v1` equivalents.
