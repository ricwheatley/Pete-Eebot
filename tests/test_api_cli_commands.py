from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from pete_e import api
from pete_e.api_routes import dependencies, logs_webhooks, status_sync
from pete_e.application.exceptions import DataAccessError, ValidationError
from pete_e.application.sync import SyncResult
from pete_e.cli import messenger as cli
from pete_e.cli.status import CheckResult
from tests.edge_security_fakes import InMemoryEdgeSecurityRepository


pytestmark = pytest.mark.contract

_WEBHOOK_SECRET = b"test-webhook-secret"
_VALID_COMMIT_SHA = "a" * 40
_REPOSITORY_ID = 1044067254


def _signed_webhook_request(
    payload: dict[str, object],
    *,
    event: str = "push",
) -> tuple[bytes, dict[str, str]]:
    payload.setdefault("repository", {"id": _REPOSITORY_ID})
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(_WEBHOOK_SECRET, body, hashlib.sha256).hexdigest()
    return body, {
        "Content-Type": "application/json",
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": "test-delivery",
        "X-Hub-Signature-256": f"sha256={signature}",
    }


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch):
    edge_repository = InMemoryEdgeSecurityRepository()
    monkeypatch.setattr(dependencies.settings, "PETEEEBOT_API_KEY", "test-key")
    monkeypatch.setattr(logs_webhooks.settings, "PETEEEBOT_GITHUB_REPOSITORY_ID", _REPOSITORY_ID)
    monkeypatch.setattr(logs_webhooks.settings, "PETEEEBOT_GITHUB_DEPLOY_REF", "refs/heads/main")
    monkeypatch.setattr(logs_webhooks.settings, "PETEEEBOT_WEBHOOK_MAX_BODY_BYTES", 262144)
    monkeypatch.setattr(logs_webhooks, "get_edge_security_repository", lambda: edge_repository)
    monkeypatch.setattr(status_sync, "enforce_command_rate_limit", lambda *_args, **_kwargs: None)
    with TestClient(api.app) as test_client:
        yield test_client


def test_status_endpoint_returns_checks(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    checks = [
        CheckResult(name="DB", ok=True, detail="5ms"),
        CheckResult(name="Dropbox", ok=False, detail="timeout"),
    ]

    class _StatusServiceFake:
        def run_checks(self, timeout: float):
            assert timeout == 1.5
            return checks

    monkeypatch.setattr(status_sync, "get_status_service", lambda: _StatusServiceFake())
    monkeypatch.setattr(
        status_sync.alerts,
        "emit_auth_expiry_if_needed",
        lambda **_kwargs: None,
    )

    response = client.get(
        "/api/v1/status",
        params={"timeout": "1.5"},
        headers={"X-API-Key": "test-key"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["checks"] == [
        {"name": "DB", "ok": True, "detail": "5ms"},
        {"name": "Dropbox", "ok": False, "detail": "timeout"},
    ]
    assert "Dropbox" in response.json()["summary"]


def test_status_endpoint_requires_valid_api_key(client: TestClient):
    response = client.get("/api/v1/status")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_sync_endpoint_returns_sync_result(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, tuple[int, int]] = {}

    def fake_sync(days: int, retries: int):
        captured["args"] = (days, retries)
        return SyncResult(
            success=True,
            attempts=2,
            failed_sources=["Dropbox"],
            source_statuses={"Dropbox": "failed", "Withings": "ok"},
            label="daily",
            undelivered_alerts=["Alert A"],
        )

    class _JobServiceFake:
        def run_callback(self, *, callback, **_kwargs):
            return callback()

        def record_command_event(self, **_kwargs):
            return None

    monkeypatch.setattr(status_sync, "run_sync_with_retries", fake_sync)
    monkeypatch.setattr(status_sync, "get_job_service", lambda: _JobServiceFake())
    monkeypatch.setattr(status_sync, "prepare_job_context", lambda *_args: "sync-test-job")
    monkeypatch.setattr(status_sync, "enforce_command_rate_limit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(status_sync, "audit_command_event", lambda *_args, **_kwargs: None)

    response = client.post(
        "/api/v1/sync",
        params={"days": "3", "retries": "1"},
        headers={"X-API-Key": "test-key"},
    )

    assert response.status_code == 200
    assert captured["args"] == (3, 1)
    assert response.json()["success"] is True
    assert response.json()["attempts"] == 2
    assert response.json()["failed_sources"] == ["Dropbox"]
    assert response.json()["source_statuses"]["Withings"] == "ok"
    assert "Alert A" in response.json()["undelivered_alerts"]
    assert response.json()["job_id"] == "sync-test-job"


def test_logs_endpoint_returns_tail(
    client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    log_path = tmp_path / "pete_history.log"
    log_path.write_text("line1\nline2\nline3\nline4\n", encoding="utf-8")
    monkeypatch.setattr(
        type(logs_webhooks.settings),
        "log_path",
        property(lambda self: log_path),
    )

    response = client.get(
        "/api/v1/logs",
        params={"lines": "2"},
        headers={"X-API-Key": "test-key"},
    )

    assert response.status_code == 200
    assert response.json()["path"].endswith("pete_history.log")
    assert response.json()["lines"] == ["line3", "line4"]


@pytest.mark.parametrize(
    ("event", "payload"),
    [
        (
            "push",
            {
                "ref": "refs/heads/feature/example",
                "after": _VALID_COMMIT_SHA,
                "deleted": False,
            },
        ),
        (
            "push",
            {
                "ref": "refs/heads/feature/example",
                "after": "0" * 40,
                "deleted": True,
            },
        ),
        (
            "push",
            {
                "ref": "refs/heads/main",
                "after": "0" * 40,
                "deleted": True,
            },
        ),
        (
            "push",
            {
                "ref": "refs/heads/main",
                "after": "0" * 40,
                "deleted": False,
            },
        ),
        ("push", {"ref": "refs/heads/main", "deleted": False}),
        ("ping", {"zen": "Keep it logically awesome."}),
    ],
)
def test_webhook_rejects_events_that_are_not_main_branch_pushes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    event: str,
    payload: dict[str, object],
) -> None:
    audits: list[dict[str, object]] = []

    def unexpected(*_args, **_kwargs):
        raise AssertionError("ignored webhook attempted to create a deployment job")

    monkeypatch.setattr(logs_webhooks, "configured_webhook_secret", lambda: _WEBHOOK_SECRET)
    monkeypatch.setattr(logs_webhooks, "enforce_command_rate_limit", unexpected)
    monkeypatch.setattr(logs_webhooks, "prepare_job_context", unexpected)
    monkeypatch.setattr(logs_webhooks, "get_job_service", unexpected)
    monkeypatch.setattr(
        logs_webhooks,
        "audit_command_event",
        lambda *_args, **kwargs: audits.append(kwargs),
    )
    body, headers = _signed_webhook_request(payload, event=event)

    response = client.post("/api/v1/webhook", content=body, headers=headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_webhook"
    assert audits == []


def test_webhook_enqueues_only_valid_main_branch_push(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enqueued: list[dict[str, object]] = []
    rate_limits: list[tuple[object, str]] = []

    class _DeployJobService:
        def dispatch_external(self, **kwargs):
            enqueued.append(kwargs)

    monkeypatch.setattr(logs_webhooks, "configured_webhook_secret", lambda: _WEBHOOK_SECRET)
    monkeypatch.setattr(
        logs_webhooks,
        "enforce_command_rate_limit",
        lambda request, operation: rate_limits.append((request, operation)),
    )
    monkeypatch.setattr(logs_webhooks, "prepare_job_context", lambda *_args: "deploy-job")
    monkeypatch.setattr(logs_webhooks, "get_job_service", lambda: _DeployJobService())
    monkeypatch.setattr(
        logs_webhooks,
        "configured_deploy_dispatch_command",
        lambda job_id: ["sudo", "-n", "/usr/local/sbin/peteeebot-dispatch-deploy", job_id],
    )
    monkeypatch.setattr(
        logs_webhooks,
        "get_or_create_correlation_id",
        lambda _request: "deploy-correlation",
    )
    monkeypatch.setattr(logs_webhooks, "audit_command_event", lambda *_args, **_kwargs: None)
    payload = {
        "ref": "refs/heads/main",
        "after": _VALID_COMMIT_SHA,
        "deleted": False,
    }
    body, headers = _signed_webhook_request(payload)

    response = client.post("/api/v1/webhook", content=body, headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "Deployment triggered"
    assert len(enqueued) == 1
    assert rate_limits[0][1] == "deploy"
    assert enqueued[0]["request_summary"]["ref"] == "refs/heads/main"
    assert enqueued[0]["dispatch_command"][-1] == "deploy-job"
    assert enqueued[0]["request_summary"]["commit_sha"] == _VALID_COMMIT_SHA


def test_webhook_rejects_invalid_signature_before_filtering(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected(*_args, **_kwargs):
        raise AssertionError("invalid webhook reached deployment filtering")

    monkeypatch.setattr(logs_webhooks, "configured_webhook_secret", lambda: _WEBHOOK_SECRET)
    monkeypatch.setattr(logs_webhooks, "enforce_command_rate_limit", unexpected)
    monkeypatch.setattr(logs_webhooks, "prepare_job_context", unexpected)

    response = client.post(
        "/api/v1/webhook",
        content=b'{"ref":"refs/heads/main"}',
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "push",
            "X-Hub-Signature-256": "sha256=invalid",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["message"] == "Invalid signature"


def test_deploy_dispatch_command_is_bounded_to_validated_helper_and_job_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dependencies, "configured_deploy_script_path", lambda: None)
    monkeypatch.setattr(dependencies.settings, "SUDO_BIN", "/usr/bin/sudo")
    monkeypatch.setattr(
        dependencies.settings,
        "PETEEEBOT_DEPLOY_DISPATCH_BIN",
        "/usr/local/sbin/peteeebot-dispatch-deploy",
    )
    monkeypatch.setattr(
        dependencies.settings,
        "PETEEEBOT_DEPLOY_UNIT_TEMPLATE",
        "peteeebot-deploy@.service",
    )

    assert dependencies.configured_deploy_dispatch_command("deploy-safe_123") == [
        "/usr/bin/sudo",
        "-n",
        "/usr/local/sbin/peteeebot-dispatch-deploy",
        "deploy-safe_123",
    ]
    with pytest.raises(HTTPException, match="systemd-safe"):
        dependencies.configured_deploy_dispatch_command("deploy/unsafe")


def test_sync_command_handles_data_access_error(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()

    def _explode(*_args, **_kwargs):
        raise DataAccessError("database offline")

    monkeypatch.setattr(cli, "run_sync_with_retries", _explode)
    monkeypatch.setattr(
        cli,
        "_run_cli_application_job",
        lambda *, callback, **_kwargs: callback(),
    )

    result = runner.invoke(cli.app, ["sync"])

    assert result.exit_code == 4
    assert "Manual sync failed: database offline" in result.output


def test_plan_command_handles_validation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()

    class _ExplodingOrchestrator:
        def generate_and_deploy_next_plan(self, start_date, weeks):  # noqa: ARG002
            raise ValidationError("plan validation failed")

        def close(self):
            return None

    monkeypatch.setattr(cli, "_build_orchestrator", lambda: _ExplodingOrchestrator())

    result = runner.invoke(cli.app, ["plan"])

    assert result.exit_code == 2
    assert "Plan deployment failed: plan validation failed" in result.output
