"""Independent systemd deployment worker for a previously-dispatched job."""

from __future__ import annotations

from pathlib import Path
import re
import sys

from pete_e.application.jobs import ApplicationJobService, generate_worker_id
from pete_e.config import settings
from pete_e.infrastructure.job_repository import PostgresApplicationJobRepository


_SAFE_JOB_ID = re.compile(r"[A-Za-z0-9_.-]+")


def _deployment_environment(request_summary: dict[str, object]) -> dict[str, str]:
    return {
        "WEBHOOK_DELIVERY_ID": str(request_summary.get("delivery_id") or ""),
        "GITHUB_EVENT_NAME": str(request_summary.get("event") or ""),
        "GITHUB_COMMIT_SHA": str(request_summary.get("commit_sha") or ""),
        "GITHUB_REF": str(request_summary.get("ref") or ""),
        "PETEEEBOT_DEPLOY_JOB_ID": str(request_summary.get("job_id") or ""),
    }


def run_deployment_job(job_id: str) -> int:
    if _SAFE_JOB_ID.fullmatch(job_id) is None:
        return 2
    deploy_path = Path(str(settings.DEPLOY_SCRIPT_PATH or "")).expanduser()
    if not deploy_path.is_file():
        return 2

    repository = PostgresApplicationJobRepository()
    current = repository.get(job_id)
    if current is None or current.operation != "deploy":
        return 2
    environment = _deployment_environment(
        {**dict(current.request_summary or {}), "job_id": job_id}
    )
    service = ApplicationJobService(
        repository,
        worker_id=generate_worker_id(role="deployment"),
        lease_seconds=settings.PETEEEBOT_JOB_LEASE_SECONDS,
        heartbeat_interval_seconds=settings.PETEEEBOT_JOB_HEARTBEAT_SECONDS,
        recovery_interval_seconds=settings.PETEEEBOT_JOB_RECOVERY_SECONDS,
        start_recovery=False,
    )
    try:
        persisted = service.run_handed_off_subprocess(
            job_id=job_id,
            command=[str(deploy_path)],
            timeout_seconds=settings.PETEEEBOT_PROCESS_TIMEOUT_SECONDS,
            environment=environment,
        )
        terminal = repository.get(job_id)
        if not persisted or terminal is None:
            return 3
        return 0 if terminal.status == "succeeded" else 1
    finally:
        service.close(wait=False)


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        return 2
    return run_deployment_job(arguments[0])


if __name__ == "__main__":
    raise SystemExit(main())
