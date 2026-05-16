from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from pete_e.api_routes import auth, dependencies, nutrition
from pete_e.domain.auth import AuthUser, ROLE_OPERATOR, ROLE_READ_ONLY, UserSession


class _Request:
    def __init__(
        self,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        path: str | None = None,
    ) -> None:
        self.method = method
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.query_params = {}
        self.client = SimpleNamespace(host="127.0.0.1")
        self.state = SimpleNamespace()
        if path is not None:
            self.scope = {"path": path}


class _Response:
    def __init__(self) -> None:
        self.cookies: dict[str, dict] = {}
        self.deleted: dict[str, dict] = {}

    def set_cookie(self, key: str, value: str, **kwargs) -> None:
        self.cookies[key] = {"value": value, **kwargs}

    def delete_cookie(self, key: str, **kwargs) -> None:
        self.deleted[key] = kwargs


class _UserService:
    def __init__(self, user: AuthUser, *, token: str = "session-token", mfa_code: str | None = None) -> None:
        self.user = user
        self.token = token
        self.mfa_code = mfa_code
        self.revoked: str | None = None

    def authenticate_user(self, login: str, password: str):
        if login == "pete" and password == "password123":
            return self.user
        return None

    def create_session(self, user, *, ip_address=None, user_agent=None):
        session = UserSession(
            id=1,
            user_id=user.id,
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=12),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return SimpleNamespace(session=session, token=self.token)

    def validate_session_token(self, token: str):
        return self.user if token == self.token else None

    def revoke_session_token(self, token: str) -> None:
        self.revoked = token

    def user_requires_mfa(self, user) -> bool:
        return bool(self.mfa_code)

    def verify_mfa_code(self, user, code: str) -> bool:
        return code == self.mfa_code


class _NutritionService:
    def log_macros(self, payload):
        return {"id": 7, **payload}


@pytest.fixture(autouse=True)
def reset_login_attempts():
    dependencies.reset_login_attempts()
    yield
    dependencies.reset_login_attempts()


@pytest.fixture()
def auth_user() -> AuthUser:
    return AuthUser(
        id=1,
        username="pete",
        email="pete@example.com",
        display_name="Pete",
        roles=(ROLE_OPERATOR,),
        is_active=True,
    )


def test_login_sets_http_only_session_cookie_and_readable_csrf_cookie(
    monkeypatch: pytest.MonkeyPatch,
    auth_user: AuthUser,
) -> None:
    service = _UserService(auth_user)
    monkeypatch.setattr(auth, "get_user_service", lambda: service)
    monkeypatch.setattr(dependencies.settings, "PETEEEBOT_SESSION_COOKIE_SECURE", True, raising=False)
    monkeypatch.setattr(dependencies.settings, "PETEEEBOT_SESSION_COOKIE_SAMESITE", "lax", raising=False)
    response = _Response()

    payload = auth.login(
        request=_Request(method="POST", headers={"User-Agent": "pytest"}),
        response=response,
        payload={"login": "pete", "password": "password123"},
    )

    session_cookie = response.cookies[dependencies.session_cookie_name()]
    csrf_cookie = response.cookies[dependencies.csrf_cookie_name()]
    assert payload["authenticated"] is True
    assert payload["user"]["username"] == "pete"
    assert session_cookie["value"] == service.token
    assert session_cookie["httponly"] is True
    assert session_cookie["secure"] is True
    assert session_cookie["samesite"] == "lax"
    assert csrf_cookie["httponly"] is False
    assert csrf_cookie["value"] == payload["csrf_token"]


def test_failed_login_imposes_retry_backoff(
    monkeypatch: pytest.MonkeyPatch,
    auth_user: AuthUser,
) -> None:
    dependencies.reset_login_attempts()
    monkeypatch.setattr(auth, "get_user_service", lambda: _UserService(auth_user))
    monkeypatch.setattr(dependencies, "DEFAULT_LOGIN_RATE_LIMIT_MAX_ATTEMPTS", 5)
    monkeypatch.setattr(dependencies, "DEFAULT_LOGIN_BACKOFF_BASE_SECONDS", 30.0)

    with pytest.raises(auth.HTTPException) as first:
        auth.login(
            request=_Request(method="POST"),
            response=_Response(),
            payload={"login": "pete", "password": "wrong"},
        )

    assert first.value.status_code == 401
    with pytest.raises(auth.HTTPException) as second:
        auth.login(
            request=_Request(method="POST"),
            response=_Response(),
            payload={"login": "pete", "password": "wrong"},
        )

    assert second.value.status_code == 429
    assert second.value.detail["code"] == "login_backoff"


def test_login_returns_mfa_challenge_without_creating_session(
    monkeypatch: pytest.MonkeyPatch,
    auth_user: AuthUser,
) -> None:
    service = _UserService(auth_user, mfa_code="123456")
    monkeypatch.setattr(auth, "get_user_service", lambda: service)
    response = _Response()

    payload = auth.login(
        request=_Request(method="POST"),
        response=response,
        payload={"login": "pete", "password": "password123"},
    )

    assert payload["authenticated"] is False
    assert payload["mfa_required"] is True
    assert response.cookies == {}


def test_login_accepts_valid_mfa_code(
    monkeypatch: pytest.MonkeyPatch,
    auth_user: AuthUser,
) -> None:
    service = _UserService(auth_user, mfa_code="123456")
    monkeypatch.setattr(auth, "get_user_service", lambda: service)
    response = _Response()

    payload = auth.login(
        request=_Request(method="POST"),
        response=response,
        payload={"login": "pete", "password": "password123", "mfa_code": "123456"},
    )

    assert payload["authenticated"] is True
    assert response.cookies[dependencies.session_cookie_name()]["value"] == service.token


def test_login_rejects_invalid_mfa_code(
    monkeypatch: pytest.MonkeyPatch,
    auth_user: AuthUser,
) -> None:
    service = _UserService(auth_user, mfa_code="123456")
    monkeypatch.setattr(auth, "get_user_service", lambda: service)

    with pytest.raises(auth.HTTPException) as exc:
        auth.login(
            request=_Request(method="POST"),
            response=_Response(),
            payload={"login": "pete", "password": "password123", "mfa_code": "999999"},
        )

    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid MFA code"


def test_repeated_failed_login_locks_account_identity(
    monkeypatch: pytest.MonkeyPatch,
    auth_user: AuthUser,
) -> None:
    dependencies.reset_login_attempts()
    monkeypatch.setattr(auth, "get_user_service", lambda: _UserService(auth_user))
    monkeypatch.setattr(dependencies, "DEFAULT_LOGIN_RATE_LIMIT_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(dependencies, "DEFAULT_LOGIN_BACKOFF_BASE_SECONDS", 0.0)
    monkeypatch.setattr(dependencies, "DEFAULT_LOGIN_LOCKOUT_SECONDS", 120.0)

    with pytest.raises(auth.HTTPException):
        auth.login(
            request=_Request(method="POST"),
            response=_Response(),
            payload={"login": "pete", "password": "wrong"},
        )
    with pytest.raises(auth.HTTPException) as locked:
        auth.login(
            request=_Request(method="POST"),
            response=_Response(),
            payload={"login": "pete", "password": "wrong"},
        )

    assert locked.value.status_code == 429
    assert locked.value.detail["code"] == "login_locked"


def test_session_route_rejects_unauthenticated_browser_request() -> None:
    with pytest.raises(auth.HTTPException) as exc:
        auth.session(_Request())

    assert exc.value.status_code == 401


def test_session_route_accepts_valid_browser_cookie(
    monkeypatch: pytest.MonkeyPatch,
    auth_user: AuthUser,
) -> None:
    service = _UserService(auth_user)
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)

    payload = auth.session(_Request(cookies={dependencies.session_cookie_name(): service.token}))

    assert payload["authenticated"] is True
    assert payload["user"]["roles"] == [ROLE_OPERATOR]


def test_logout_requires_session_csrf_revokes_session_and_clears_cookies(
    monkeypatch: pytest.MonkeyPatch,
    auth_user: AuthUser,
) -> None:
    service = _UserService(auth_user)
    csrf_token = dependencies.generate_csrf_token(service.token)
    monkeypatch.setattr(auth, "get_user_service", lambda: service)
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    response = _Response()

    payload = auth.logout(
        request=_Request(
            method="POST",
            headers={dependencies.CSRF_HEADER_NAME: csrf_token},
            cookies={
                dependencies.session_cookie_name(): service.token,
                dependencies.csrf_cookie_name(): csrf_token,
            },
        ),
        response=response,
    )

    assert payload == {"authenticated": False}
    assert service.revoked == service.token
    assert dependencies.session_cookie_name() in response.deleted
    assert dependencies.csrf_cookie_name() in response.deleted


def test_state_changing_session_request_requires_csrf(
    monkeypatch: pytest.MonkeyPatch,
    auth_user: AuthUser,
) -> None:
    service = _UserService(auth_user)
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)

    with pytest.raises(nutrition.HTTPException) as exc:
        nutrition.log_macros(
            request=_Request(method="POST", cookies={dependencies.session_cookie_name(): service.token}),
            payload={"protein_g": 40},
            x_api_key=None,
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "csrf_required"


def test_state_changing_session_request_accepts_valid_csrf(
    monkeypatch: pytest.MonkeyPatch,
    auth_user: AuthUser,
) -> None:
    service = _UserService(auth_user)
    csrf_token = dependencies.generate_csrf_token(service.token)
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    monkeypatch.setattr(nutrition, "get_nutrition_service", lambda: _NutritionService())

    payload = nutrition.log_macros(
        request=_Request(
            method="POST",
            headers={dependencies.CSRF_HEADER_NAME: csrf_token},
            cookies={
                dependencies.session_cookie_name(): service.token,
                dependencies.csrf_cookie_name(): csrf_token,
            },
        ),
        payload={"protein_g": 40},
        x_api_key=None,
    )

    assert payload == {"id": 7, "protein_g": 40}


def test_api_key_state_changing_request_does_not_require_csrf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dependencies.settings, "PETEEEBOT_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(nutrition, "get_nutrition_service", lambda: _NutritionService())

    payload = nutrition.log_macros(
        request=_Request(method="POST"),
        payload={"protein_g": 40},
        x_api_key="test-key",
    )

    assert payload == {"id": 7, "protein_g": 40}


def test_read_only_session_cannot_call_operator_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_only = AuthUser(
        id=2,
        username="reader",
        email=None,
        display_name=None,
        roles=(ROLE_READ_ONLY,),
        is_active=True,
    )
    service = _UserService(read_only)
    csrf_token = dependencies.generate_csrf_token(service.token)
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)
    monkeypatch.setattr(nutrition, "get_nutrition_service", lambda: _NutritionService())

    with pytest.raises(nutrition.HTTPException) as exc:
        nutrition.log_macros(
            request=_Request(
                method="POST",
                headers={dependencies.CSRF_HEADER_NAME: csrf_token},
                cookies={
                    dependencies.session_cookie_name(): service.token,
                    dependencies.csrf_cookie_name(): csrf_token,
                },
                path="/api/v1/nutrition/log-macros",
            ),
            payload={"protein_g": 40},
            x_api_key=None,
        )

    assert exc.value.status_code == 403
