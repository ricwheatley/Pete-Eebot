# Production Readiness Signoff

Copy this template for each production launch, material deployment, host change, reverse proxy change, auth/session change, schema migration, backup change, or alerting change.

## Release

| Field | Value |
| --- | --- |
| Release/change name |  |
| Date/time |  |
| Operator |  |
| Reviewer |  |
| Host/environment |  |
| Git branch |  |
| Git SHA being deployed |  |
| Previous known-good SHA |  |
| Database target |  |
| Reverse proxy config path |  |
| Related issue/PR/doc |  |

## Scope

Summary:

- 

Out of scope:

- 

## Checklist Summary

| Area | Status | Evidence location | Owner |
| --- | --- | --- | --- |
| Deployment prerequisites | Pending |  |  |
| TLS/reverse proxy expectations | Pending |  |  |
| Auth/session/security controls | Pending |  |  |
| Backup/restore validation | Pending |  |  |
| Observability and alert tests | Pending |  |  |
| Rollback plan | Pending |  |  |

Status values: `Ready`, `Ready with accepted risk`, `Blocked`, or `Not applicable`.

## Evidence

Deployment prerequisite evidence:

```text

```

TLS/reverse proxy evidence:

```text

```

Auth/session/security evidence:

```text

```

Backup/restore evidence:

```text

```

Observability/alert evidence:

```text

```

Rollback evidence:

```text

```

## Backup and Restore

| Field | Value |
| --- | --- |
| Predeploy backup completed at |  |
| Backup artifact path |  |
| Secret backup path |  |
| Cloud backup path, if enabled |  |
| Restore validation target |  |
| Restore validation completed at |  |
| RPO accepted for this release |  |
| RTO accepted for this release |  |

## Rollback Plan

Rollback trigger criteria:

- 

Code rollback command or runbook link:

```bash

```

Database rollback decision:

- 

Proxy/config rollback decision:

- 

Feature flag/env rollback decision:

- 

Post-rollback smoke checks:

- 

## Accepted Risks

| Risk | Severity | Owner | Expiry/review date | Fallback |
| --- | --- | --- | --- | --- |
|  |  |  |  |  |

## Decision

Production readiness decision: `Approved` / `Approved with accepted risk` / `Rejected`

Approvals:

| Role | Name | Date/time | Notes |
| --- | --- | --- | --- |
| Operator |  |  |  |
| Reviewer |  |  |  |

