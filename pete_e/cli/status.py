"""Health check command support for the pete CLI."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Callable, Iterable, List, Sequence

import psycopg

from pete_e.infrastructure.db_conn import get_database_url
from pete_e.infrastructure.apple_dropbox_client import AppleDropboxClient
from pete_e.infrastructure.withings_client import WithingsClient

DEFAULT_TIMEOUT_SECONDS = 3.0


@dataclass
class CheckResult:
    """Represents a single dependency check outcome."""

    name: str
    ok: bool
    detail: str


def _format_duration(start: float) -> str:
    elapsed = perf_counter() - start
    if elapsed < 0.001:
        return "<1ms"
    return f"{int(elapsed * 1000)}ms"


def _format_exception(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        message = exc.__class__.__name__
    return message.splitlines()[0]


def check_database(timeout: float = DEFAULT_TIMEOUT_SECONDS) -> CheckResult:
    start = perf_counter()
    try:
        with psycopg.connect(get_database_url(), connect_timeout=timeout) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
    except Exception as exc:  # pragma: no cover - handled via result
        return CheckResult(name="DB", ok=False, detail=_format_exception(exc))
    return CheckResult(name="DB", ok=True, detail=_format_duration(start))


def check_dropbox(timeout: float = DEFAULT_TIMEOUT_SECONDS) -> CheckResult:
    start = perf_counter()
    try:
        client = AppleDropboxClient(request_timeout=timeout)
        detail = client.ping()
    except Exception as exc:  # pragma: no cover - handled via result
        return CheckResult(name="Dropbox", ok=False, detail=_format_exception(exc))
    if not detail:
        detail = _format_duration(start)
    return CheckResult(name="Dropbox", ok=True, detail=detail)


def check_withings(timeout: float = DEFAULT_TIMEOUT_SECONDS) -> CheckResult:
    start = perf_counter()
    try:
        client = WithingsClient(request_timeout=timeout)
        detail = client.ping()
    except Exception as exc:  # pragma: no cover - handled via result
        return CheckResult(name="Withings", ok=False, detail=_format_exception(exc))
    if not detail:
        detail = _format_duration(start)
    return CheckResult(name="Withings", ok=True, detail=detail)


def run_status_checks(
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    checks: Sequence[Callable[[], CheckResult]] | None = None,
) -> List[CheckResult]:
    """Executes dependency checks, allowing override for testing."""

    if checks is None:
        checks = (
            lambda: check_database(timeout),
            lambda: check_dropbox(timeout),
            lambda: check_withings(timeout),
        )

    return [check() for check in checks]


def render_results(results: Iterable[CheckResult]) -> str:
    lines = []
    for result in results:
        status = "OK" if result.ok else "FAIL"
        lines.append(f"{result.name:<8} {status:<4} {result.detail}")
    return "\n".join(lines)
