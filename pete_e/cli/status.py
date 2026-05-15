"""Health check command support for the pete CLI."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Callable, Iterable, List, Sequence

import psycopg

from pete_e import observability
from pete_e.infrastructure.db_conn import get_database_url
from pete_e.infrastructure.apple_dropbox_client import AppleDropboxClient
from pete_e.infrastructure.telegram_client import TelegramClient
from pete_e.infrastructure.withings_client import WithingsClient
from pete_e.infrastructure.wger_client import WgerClient

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
    """Perform format duration."""


def _format_exception(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        message = exc.__class__.__name__
    return message.splitlines()[0]
    """Perform format exception."""


def _record_result(name: str, ok: bool, start: float, *, kind: str) -> None:
    observability.record_dependency_check(
        dependency=name,
        ok=ok,
        duration_seconds=perf_counter() - start,
        kind=kind,
    )


def check_database(timeout: float = DEFAULT_TIMEOUT_SECONDS) -> CheckResult:
    start = perf_counter()
    try:
        with psycopg.connect(get_database_url(), connect_timeout=timeout) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
    except Exception as exc:  # pragma: no cover - handled via result
        _record_result("DB", False, start, kind="database")
        return CheckResult(name="DB", ok=False, detail=_format_exception(exc))
    _record_result("DB", True, start, kind="database")
    return CheckResult(name="DB", ok=True, detail=_format_duration(start))
    """Perform check database."""


def check_dropbox(timeout: float = DEFAULT_TIMEOUT_SECONDS) -> CheckResult:
    start = perf_counter()
    try:
        client = AppleDropboxClient(request_timeout=timeout)
        detail = client.ping()
    except Exception as exc:  # pragma: no cover - handled via result
        _record_result("Dropbox", False, start, kind="external_api")
        return CheckResult(name="Dropbox", ok=False, detail=_format_exception(exc))
    if not detail:
        detail = _format_duration(start)
    _record_result("Dropbox", True, start, kind="external_api")
    return CheckResult(name="Dropbox", ok=True, detail=detail)
    """Perform check dropbox."""


def check_withings(timeout: float = DEFAULT_TIMEOUT_SECONDS) -> CheckResult:
    start = perf_counter()
    try:
        client = WithingsClient(request_timeout=timeout)
        detail = client.ping()
    except Exception as exc:  # pragma: no cover - handled via result
        _record_result("Withings", False, start, kind="external_api")
        return CheckResult(name="Withings", ok=False, detail=_format_exception(exc))
    if not detail:
        detail = _format_duration(start)
    _record_result("Withings", True, start, kind="external_api")
    return CheckResult(name="Withings", ok=True, detail=detail)
    """Perform check withings."""


def check_telegram(timeout: float = DEFAULT_TIMEOUT_SECONDS) -> CheckResult:
    start = perf_counter()
    try:
        client = TelegramClient(request_timeout=timeout)
        detail = client.ping()
    except Exception as exc:  # pragma: no cover - handled via result
        _record_result("Telegram", False, start, kind="external_api")
        return CheckResult(name="Telegram", ok=False, detail=_format_exception(exc))
    if not detail:
        detail = _format_duration(start)
    _record_result("Telegram", True, start, kind="external_api")
    return CheckResult(name="Telegram", ok=True, detail=detail)
    """Perform check telegram."""


def check_wger(timeout: float = DEFAULT_TIMEOUT_SECONDS) -> CheckResult:
    start = perf_counter()
    try:
        client = WgerClient(timeout=timeout)
        detail = client.ping()
    except Exception as exc:  # pragma: no cover - handled via result
        _record_result("Wger", False, start, kind="external_api")
        return CheckResult(name="Wger", ok=False, detail=_format_exception(exc))
    if not detail:
        detail = _format_duration(start)
    _record_result("Wger", True, start, kind="external_api")
    return CheckResult(name="Wger", ok=True, detail=detail)
    """Perform check wger."""


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
            lambda: check_telegram(timeout),
            lambda: check_wger(timeout),
        )

    return [check() for check in checks]


def render_results(results: Iterable[CheckResult]) -> str:
    lines = []
    for result in results:
        status = "OK" if result.ok else "FAIL"
        lines.append(f"{result.name:<8} {status:<4} {result.detail}")
    return "\n".join(lines)
    """Perform render results."""
