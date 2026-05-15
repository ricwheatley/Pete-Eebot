from __future__ import annotations

from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from pete_e.application.exceptions import ConflictError
from pete_e.cli import messenger
from pete_e.cli.messenger import app
from pete_e.domain.auth import AuthUser, ROLE_OWNER


runner = CliRunner()


class _BootstrapService:
    def __init__(self, *, fail: Exception | None = None) -> None:
        self.fail = fail
        self.bootstrap_calls: list[dict[str, object]] = []
        self.reset_calls: list[dict[str, object]] = []

    def bootstrap_owner(self, *, username, email, display_name, password):
        if self.fail is not None:
            raise self.fail
        self.bootstrap_calls.append(
            {
                "username": username,
                "email": email,
                "display_name": display_name,
                "password": password,
            }
        )
        return AuthUser(
            id=42,
            username=username,
            email=email,
            display_name=display_name,
            roles=(ROLE_OWNER,),
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )

    def reset_owner_password(self, *, login, password):
        if self.fail is not None:
            raise self.fail
        self.reset_calls.append({"login": login, "password": password})
        return AuthUser(
            id=42,
            username="owner",
            email="owner@example.com",
            display_name="Owner",
            roles=(ROLE_OWNER,),
            is_active=True,
        )


def _patch_bootstrap_service(monkeypatch: pytest.MonkeyPatch, service: _BootstrapService) -> None:
    monkeypatch.setattr(messenger, "PostgresUserRepository", lambda: object())
    monkeypatch.setattr(messenger, "UserService", lambda _repo: service)


def _output(result) -> str:
    return getattr(result, "output", result.stdout)


def test_bootstrap_owner_cli_uses_env_password_without_echoing_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _BootstrapService()
    _patch_bootstrap_service(monkeypatch, service)
    monkeypatch.setenv("PETEEEBOT_BOOTSTRAP_OWNER_PASSWORD", "password123")

    result = runner.invoke(
        app,
        [
            "bootstrap-owner",
            "--username",
            "owner",
            "--email",
            "owner@example.com",
            "--display-name",
            "Owner",
        ],
    )

    assert result.exit_code == 0
    assert service.bootstrap_calls == [
        {
            "username": "owner",
            "email": "owner@example.com",
            "display_name": "Owner",
            "password": "password123",
        }
    ]
    assert "Owner user created: owner" in _output(result)
    assert "password123" not in _output(result)


def test_bootstrap_owner_cli_rejects_duplicate_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _BootstrapService(fail=ConflictError("an owner user already exists", code="owner_already_exists"))
    _patch_bootstrap_service(monkeypatch, service)
    monkeypatch.setenv("PETEEEBOT_BOOTSTRAP_OWNER_PASSWORD", "password123")

    result = runner.invoke(app, ["bootstrap-owner", "--username", "owner"])

    assert result.exit_code == 2
    assert "Owner bootstrap failed: an owner user already exists" in _output(result)


def test_reset_owner_password_cli_revokes_existing_owner_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _BootstrapService()
    _patch_bootstrap_service(monkeypatch, service)
    audit_events: list[dict[str, object]] = []
    monkeypatch.setattr(messenger.log_utils, "log_checkpoint", lambda **kwargs: audit_events.append(kwargs))
    monkeypatch.setenv("PETEEEBOT_RESET_OWNER_PASSWORD", "new-password123")

    result = runner.invoke(app, ["reset-owner-password", "--login", "owner@example.com"])

    assert result.exit_code == 0
    assert service.reset_calls == [{"login": "owner@example.com", "password": "new-password123"}]
    assert "Owner password reset: owner" in _output(result)
    assert "new-password123" not in _output(result)
    assert audit_events == [
        {
            "checkpoint": "owner_password_recovery",
            "outcome": "succeeded",
            "correlation": {
                "actor": "local_cli",
                "target_user_id": 42,
                "target_username": "owner",
                "target_roles": [ROLE_OWNER],
            },
            "summary": {
                "target_login": "owner@example.com",
                "method": "local_cli",
                "sessions_revoked": True,
            },
            "level": "INFO",
            "tag": "AUDIT",
        }
    ]
    assert "new-password123" not in repr(audit_events)


def test_reset_owner_password_cli_audits_failed_attempt_without_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _BootstrapService(fail=ConflictError("target rejected", code="target_rejected"))
    _patch_bootstrap_service(monkeypatch, service)
    audit_events: list[dict[str, object]] = []
    monkeypatch.setattr(messenger.log_utils, "log_checkpoint", lambda **kwargs: audit_events.append(kwargs))
    monkeypatch.setenv("PETEEEBOT_RESET_OWNER_PASSWORD", "new-password123")

    result = runner.invoke(app, ["reset-owner-password", "--login", "viewer@example.com"])

    assert result.exit_code == 2
    assert "Owner password reset failed: target rejected" in _output(result)
    assert audit_events == [
        {
            "checkpoint": "owner_password_recovery",
            "outcome": "failed",
            "correlation": {"actor": "local_cli"},
            "summary": {
                "target_login": "viewer@example.com",
                "method": "local_cli",
                "sessions_revoked": False,
                "error_code": "target_rejected",
            },
            "level": "WARNING",
            "tag": "AUDIT",
        }
    ]
    assert "new-password123" not in _output(result)
    assert "new-password123" not in repr(audit_events)
