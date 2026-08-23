"""Health check command support for the pete CLI."""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass
from time import perf_counter
from typing import Callable, Iterable, List, Sequence

from pete_e import observability
from pete_e.application import alerts
from pete_e.config import settings
from pete_e.infrastructure.db_conn import get_database_url
from pete_e.infrastructure.schema_migrations import inspect_database
from pete_e.infrastructure.apple_dropbox_client import AppleDropboxClient
from pete_e.infrastructure.ollama_client import OllamaChatClient
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
        schema = inspect_database(get_database_url(), timeout=timeout)
        if not schema.compatible:
            detail = (
                f"schema {schema.state}: current={schema.current_revision or 'none'} "
                f"required={schema.head_revision}; {schema.detail}"
            )
            _record_result("DB", False, start, kind="database")
            return CheckResult(name="DB", ok=False, detail=detail)
    except Exception as exc:  # pragma: no cover - handled via result
        _record_result("DB", False, start, kind="database")
        return CheckResult(name="DB", ok=False, detail=_format_exception(exc))
    _record_result("DB", True, start, kind="database")
    return CheckResult(
        name="DB",
        ok=True,
        detail=f"schema {schema.head_revision} ({_format_duration(start)})",
    )
    """Perform check database."""


def check_dropbox(timeout: float = DEFAULT_TIMEOUT_SECONDS) -> CheckResult:
    start = perf_counter()
    try:
        client = AppleDropboxClient(request_timeout=timeout)
        detail = client.ping()
    except Exception as exc:  # pragma: no cover - handled via result
        detail = _format_exception(exc)
        _record_result("Dropbox", False, start, kind="external_api")
        alerts.emit_auth_expiry_if_needed(provider="Dropbox", detail=detail)
        return CheckResult(name="Dropbox", ok=False, detail=detail)
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
        detail = _format_exception(exc)
        _record_result("Withings", False, start, kind="external_api")
        alerts.emit_auth_expiry_if_needed(provider="Withings", detail=detail)
        return CheckResult(name="Withings", ok=False, detail=detail)
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
        detail = _format_exception(exc)
        _record_result("Wger", False, start, kind="external_api")
        alerts.emit_auth_expiry_if_needed(provider="Wger", detail=detail)
        return CheckResult(name="Wger", ok=False, detail=detail)
    if not detail:
        detail = _format_duration(start)
    _record_result("Wger", True, start, kind="external_api")
    return CheckResult(name="Wger", ok=True, detail=detail)
    """Perform check wger."""


def check_llm(timeout: float = DEFAULT_TIMEOUT_SECONDS) -> CheckResult:
    start = perf_counter()
    if not bool(getattr(settings, "PETEEEBOT_LLM_ENABLED", False)):
        _record_result("LLM", True, start, kind="external_api")
        return CheckResult(name="LLM", ok=True, detail="disabled")

    try:
        client = OllamaChatClient(
            base_url=str(getattr(settings, "PETEEEBOT_LLM_BASE_URL", "http://127.0.0.1:11434")),
            model=str(getattr(settings, "PETEEEBOT_LLM_MODEL", "qwen2.5:1.5b")),
            timeout_seconds=timeout,
        )
        detail = client.ping()
    except Exception as exc:  # pragma: no cover - handled via result
        detail = _format_exception(exc)
        _record_result("LLM", False, start, kind="external_api")
        return CheckResult(name="LLM", ok=False, detail=detail)
    if not detail:
        detail = _format_duration(start)
    _record_result("LLM", True, start, kind="external_api")
    return CheckResult(name="LLM", ok=True, detail=detail)
    """Perform check llm."""


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
            lambda: check_llm(timeout),
        )

    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=len(checks),
        thread_name_prefix="status-check",
    )
    try:
        futures = [executor.submit(check) for check in checks]
        return [future.result() for future in futures]
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def run_readiness_checks(*, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> List[CheckResult]:
    """Check only local runtime prerequisites; never call external providers."""

    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="readiness-check",
    )
    future = executor.submit(check_database, timeout)
    try:
        return [future.result(timeout=timeout)]
    except concurrent.futures.TimeoutError:
        future.cancel()
        return [CheckResult(name="DB", ok=False, detail="readiness deadline exceeded")]
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def render_results(results: Iterable[CheckResult]) -> str:
    lines = []
    for result in results:
        status = "OK" if result.ok else "FAIL"
        lines.append(f"{result.name:<8} {status:<4} {result.detail}")
    return "\n".join(lines)
    """Perform render results."""
