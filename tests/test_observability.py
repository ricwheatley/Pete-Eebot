from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest

from pete_e import observability
from pete_e.api_routes import dependencies, status_sync
from pete_e.application import alerts
from pete_e.application.api_services import MetricsService
from pete_e.cli.status import CheckResult
from pete_e.infrastructure.decorators import retry_on_network_error


class _Request:
    query_params: dict[str, str] = {}


def _response_payload(response):
    if isinstance(response, dict):
        return response
    content = getattr(response, "content", None)
    if content is not None:
        return content
    body = getattr(response, "body", b"{}")
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    return json.loads(body)


def _response_text(response) -> str:
    if isinstance(response, str):
        return response
    body = getattr(response, "body", b"")
    if isinstance(body, bytes):
        return body.decode("utf-8")
    return str(body)


def test_guarded_job_emits_latency_and_success_metrics() -> None:
    observability.reset_metrics()

    result = dependencies.run_guarded_high_risk_operation("sync", lambda: "ok")

    assert result == "ok"
    metrics = observability.render_prometheus()
    assert 'peteeebot_job_runs_total{operation="sync",outcome="succeeded"} 1' in metrics
    assert 'peteeebot_job_duration_seconds_count{operation="sync",outcome="succeeded"} 1' in metrics


def test_guarded_job_failure_emits_failure_metric() -> None:
    observability.reset_metrics()

    with pytest.raises(RuntimeError):
        dependencies.run_guarded_high_risk_operation("sync", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    metrics = observability.render_prometheus()
    assert 'peteeebot_job_runs_total{operation="sync",outcome="failed"} 1' in metrics
    assert 'peteeebot_job_failures_total{operation="sync",outcome="failed"} 1' in metrics


def test_external_api_retry_emits_retry_metric() -> None:
    observability.reset_metrics()

    class RetryableError(RuntimeError):
        status_code = 503

    class DummyClient:
        max_retries = 2
        backoff_base = 0

        def __init__(self):
            self.calls = 0

        def _should_retry(self, status: int) -> bool:
            return status == 503

        @retry_on_network_error(lambda self, status: self._should_retry(status), exception_types=(RetryableError,))
        def request(self, method: str, path: str) -> str:
            self.calls += 1
            if self.calls == 1:
                raise RetryableError("temporary")
            return "ok"

    assert DummyClient().request("GET", "/resource") == "ok"
    metrics = observability.render_prometheus()
    assert 'peteeebot_job_retries_total{operation="external_api_request",source="DummyClient"} 1' in metrics


def test_dependency_check_emits_external_api_health_metric() -> None:
    observability.reset_metrics()

    observability.record_dependency_check(
        dependency="Withings",
        ok=False,
        duration_seconds=0.25,
        kind="external_api",
    )

    metrics = observability.render_prometheus()
    assert 'peteeebot_external_api_health{dependency="Withings"} 0' in metrics
    assert 'peteeebot_external_api_failures_total{dependency="Withings"} 1' in metrics
    assert 'peteeebot_external_api_latency_seconds_count{dependency="Withings",outcome="failed"} 1' in metrics


def test_stale_ingest_alert_emits_structured_metric(monkeypatch) -> None:
    observability.reset_metrics()
    alerts.reset_alert_state()
    monkeypatch.setenv("PETEEEBOT_ALERT_TELEGRAM_ENABLED", "0")
    monkeypatch.setenv("PETEEEBOT_ALERT_DEDUPE_SECONDS", "0")
    monkeypatch.setenv("PETEEEBOT_STALE_INGEST_ALERT_DAYS", "3")

    payload = MetricsService(dal=None)._coach_data_quality(
        rows=[
            {
                "date": date(2026, 5, 10),
                "weight_kg": 88.0,
                "sleep_asleep_minutes": 420,
                "hr_resting": 50,
                "hrv_sdnn_ms": 45,
                "strength_volume_kg": 5000,
            }
        ],
        last_7=[],
        target_date=date(2026, 5, 15),
    )

    assert payload["stale_days"] == 5
    metrics = observability.render_prometheus()
    assert 'peteeebot_alert_events_total{alert_type="stale_ingest",outcome="emitted",severity="P2"} 1' in metrics
    assert 'peteeebot_alert_active{alert_type="stale_ingest",severity="P2"} 1' in metrics


def test_readyz_returns_503_when_dependency_check_fails(monkeypatch) -> None:
    observability.reset_metrics()
    alerts.reset_alert_state()
    monkeypatch.setenv("PETEEEBOT_ALERT_TELEGRAM_ENABLED", "0")
    monkeypatch.setenv("PETEEEBOT_ALERT_DEDUPE_SECONDS", "0")

    class _StatusService:
        def run_checks(self, timeout):
            assert timeout == 1.2
            return [
                CheckResult("DB", True, "2ms"),
                CheckResult("Withings", False, "token expired"),
            ]

    monkeypatch.setattr(status_sync, "get_status_service", lambda: _StatusService())

    response = status_sync.readyz(timeout=1.2)

    assert getattr(response, "status_code", 200) == 503
    payload = _response_payload(response)
    assert payload["ok"] is False
    assert payload["checks"][1] == {"name": "Withings", "ok": False, "detail": "token expired"}
    metrics = observability.render_prometheus()
    assert 'peteeebot_alert_events_total{alert_type="auth_expiry",outcome="emitted",severity="P2"} 1' in metrics


def test_readyz_returns_200_when_dependencies_are_healthy(monkeypatch) -> None:
    class _StatusService:
        def run_checks(self, timeout):
            return [CheckResult("DB", True, "2ms"), CheckResult("Wger", True, "wger.de")]

    monkeypatch.setattr(status_sync, "get_status_service", lambda: _StatusService())

    response = status_sync.readyz(timeout=0.5)

    assert getattr(response, "status_code", 200) == 200
    assert _response_payload(response)["ok"] is True


def test_prometheus_metrics_endpoint_requires_api_key_and_returns_text(monkeypatch) -> None:
    observability.reset_metrics()
    observability.record_job_completed(operation="sync", outcome="succeeded", duration_seconds=0.1)
    monkeypatch.setattr(dependencies.settings, "PETEEEBOT_API_KEY", "test-key", raising=False)

    response = status_sync.prometheus_metrics(request=_Request(), x_api_key="test-key")

    text = _response_text(response)
    assert "# TYPE peteeebot_job_runs_total counter" in text
    assert 'peteeebot_job_runs_total{operation="sync",outcome="succeeded"} 1' in text


def test_repeated_failed_jobs_emit_alert_metric(monkeypatch) -> None:
    observability.reset_metrics()
    alerts.reset_alert_state()
    monkeypatch.setenv("PETEEEBOT_ALERT_TELEGRAM_ENABLED", "0")
    monkeypatch.setenv("PETEEEBOT_ALERT_DEDUPE_SECONDS", "0")
    monkeypatch.setenv("PETEEEBOT_REPEATED_FAILURE_ALERT_THRESHOLD", "2")

    for _ in range(2):
        result = dependencies.run_guarded_high_risk_operation(
            "sync",
            lambda: SimpleNamespace(success=False),
        )
        assert result.success is False

    metrics = observability.render_prometheus()
    assert 'peteeebot_job_failures_total{operation="sync",outcome="failed"} 2' in metrics
    assert 'peteeebot_alert_events_total{alert_type="repeated_failures",outcome="emitted",severity="P2"} 1' in metrics
