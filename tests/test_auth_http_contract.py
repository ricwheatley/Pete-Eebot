from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from pete_e import api_logging
from pete_e.api_errors import install_api_error_handlers
from pete_e.api_routes import auth, dependencies
from pete_e.domain.auth import AuthUser, ROLE_OPERATOR, UserSession
from tests.edge_security_fakes import InMemoryEdgeSecurityRepository


pytestmark = pytest.mark.contract

_LOGIN = "synthetic-user"
_PASSWORD = "synthetic-password"
_MFA_CODE = "246810"


class _UserService:
    def __init__(self, user: AuthUser) -> None:
        self.user = user
        self.mfa_code: str | None = None
        self.authenticate_calls: list[tuple[str, str]] = []
        self.mfa_calls: list[str] = []

    def authenticate_user(self, login: str, password: str):
        self.authenticate_calls.append((login, password))
        if login == _LOGIN and password == _PASSWORD:
            return self.user
        return None

    def user_requires_mfa(self, user: AuthUser) -> bool:  # noqa: ARG002
        return self.mfa_code is not None

    def verify_mfa_code(self, user: AuthUser, code: str) -> bool:  # noqa: ARG002
        self.mfa_calls.append(code)
        return code == self.mfa_code

    def create_session(self, user: AuthUser, *, ip_address=None, user_agent=None):
        return SimpleNamespace(
            session=UserSession(
                id=1,
                user_id=user.id,
                created_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(hours=12),
                ip_address=ip_address,
                user_agent=user_agent,
            ),
            token="synthetic-session-token",
        )


@pytest.fixture()
def auth_boundary(monkeypatch: pytest.MonkeyPatch):
    user = AuthUser(
        id=1,
        username=_LOGIN,
        email=None,
        display_name="Synthetic User",
        roles=(ROLE_OPERATOR,),
        is_active=True,
    )
    service = _UserService(user)
    repository = InMemoryEdgeSecurityRepository()
    events: list[dict[str, object]] = []
    monkeypatch.setattr(auth, "get_user_service", lambda: service)
    monkeypatch.setattr(
        dependencies, "get_edge_security_repository", lambda: repository
    )
    monkeypatch.setattr(
        auth.log_utils, "log_event", lambda **values: events.append(values)
    )

    app = FastAPI()
    install_api_error_handlers(app)
    api_logging.install_request_logging_middleware(app)
    app.include_router(auth.router)
    with TestClient(app) as client:
        yield client, service, events


def test_urlencoded_login_reaches_authentication_and_sets_session(
    auth_boundary,
) -> None:
    client, service, _events = auth_boundary

    response = client.post(
        "/auth/login",
        data={"login": _LOGIN, "password": _PASSWORD, "mfa_code": ""},
    )

    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert response.json()["user"]["username"] == _LOGIN
    assert service.authenticate_calls == [(_LOGIN, _PASSWORD)]
    assert dependencies.session_cookie_name() in response.cookies
    assert dependencies.csrf_cookie_name() in response.cookies


def test_json_login_contract_remains_supported(auth_boundary) -> None:
    client, service, _events = auth_boundary

    response = client.post(
        "/auth/login",
        json={"login": _LOGIN, "password": _PASSWORD},
    )

    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert service.authenticate_calls == [(_LOGIN, _PASSWORD)]


def test_login_openapi_documents_only_evidenced_media_types(auth_boundary) -> None:
    client, _service, _events = auth_boundary

    content = client.app.openapi()["paths"]["/auth/login"]["post"]["requestBody"][
        "content"
    ]

    assert set(content) == {
        "application/json",
        "application/x-www-form-urlencoded",
    }


def test_urlencoded_invalid_credentials_return_401_without_secret_echo(
    auth_boundary,
) -> None:
    client, service, events = auth_boundary
    invalid_password = "invalid-password-sentinel"

    response = client.post(
        "/auth/login",
        data={"login": _LOGIN, "password": invalid_password},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert response.json()["error"]["message"] == "Invalid login or password"
    assert service.authenticate_calls == [(_LOGIN, invalid_password)]
    assert invalid_password not in response.text
    assert invalid_password not in json.dumps(events)


def test_urlencoded_mfa_challenge_and_valid_code_preserve_session_semantics(
    auth_boundary,
) -> None:
    client, service, _events = auth_boundary
    service.mfa_code = _MFA_CODE

    challenge = client.post(
        "/auth/login",
        data={"login": _LOGIN, "password": _PASSWORD, "mfa_code": ""},
    )
    authenticated = client.post(
        "/auth/login",
        data={"login": _LOGIN, "password": _PASSWORD, "mfa_code": _MFA_CODE},
    )

    assert challenge.status_code == 200
    assert challenge.json()["authenticated"] is False
    assert challenge.json()["mfa_required"] is True
    assert dependencies.session_cookie_name() not in challenge.cookies
    assert authenticated.status_code == 200
    assert authenticated.json()["authenticated"] is True
    assert service.mfa_calls == [_MFA_CODE]


def test_urlencoded_invalid_mfa_code_returns_401(auth_boundary) -> None:
    client, service, events = auth_boundary
    service.mfa_code = _MFA_CODE
    invalid_code = "invalid-mfa-sentinel"

    response = client.post(
        "/auth/login",
        data={"login": _LOGIN, "password": _PASSWORD, "mfa_code": invalid_code},
    )

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid MFA code"
    assert invalid_code not in response.text
    assert invalid_code not in json.dumps(events)


def test_malformed_urlencoded_login_returns_safe_structured_422(auth_boundary) -> None:
    client, service, events = auth_boundary
    password = "malformed-password-sentinel"
    mfa_code = "malformed-mfa-sentinel"
    raw_body = (
        f"login={_LOGIN}&password={password}&mfa_code={mfa_code}&bad=".encode()
        + b"\xff"
    )

    response = client.post(
        "/auth/login",
        content=raw_body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["details"]["errors"][0]["type"] == "form_parsing"
    assert service.authenticate_calls == []
    serialized_events = json.dumps(events)
    for secret in (password, mfa_code, raw_body.decode("utf-8", errors="ignore")):
        assert secret not in response.text
        assert secret not in serialized_events


def test_login_rejects_multipart_instead_of_broadening_the_contract(
    auth_boundary,
) -> None:
    client, service, _events = auth_boundary

    response = client.post(
        "/auth/login",
        files={
            "login": (None, _LOGIN),
            "password": (None, _PASSWORD),
        },
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"
    assert service.authenticate_calls == []
