from __future__ import annotations

from types import SimpleNamespace

import pytest

from pete_e import api
from pete_e.api_routes import dependencies, web
from pete_e.domain.auth import AuthUser, ROLE_OPERATOR, ROLE_OWNER, ROLE_READ_ONLY


class _Request:
    def __init__(
        self,
        *,
        path: str = "/console/status",
        cookies: dict[str, str] | None = None,
        query_params: dict[str, str] | None = None,
    ) -> None:
        self.method = "GET"
        self.headers = {}
        self.cookies = cookies or {}
        self.query_params = query_params or {}
        self.client = SimpleNamespace(host="127.0.0.1")
        self.scope = {"path": path}
        self.state = SimpleNamespace()


class _UserService:
    def __init__(self, user: AuthUser, *, token: str = "session-token") -> None:
        self.user = user
        self.token = token

    def validate_session_token(self, token: str):
        return self.user if token == self.token else None


def _body(response) -> str:
    body = getattr(response, "body", b"")
    if isinstance(body, bytes):
        return body.decode("utf-8")
    return str(body)


def _location(response) -> str | None:
    headers = getattr(response, "headers", {}) or {}
    return headers.get("location") or headers.get("Location")


def _user(*roles: str) -> AuthUser:
    return AuthUser(
        id=1,
        username="pete",
        email="pete@example.com",
        display_name="Pete",
        roles=roles or (ROLE_READ_ONLY,),
        is_active=True,
    )


def test_console_route_redirects_unauthenticated_browser_request() -> None:
    response = web.console_status(_Request(path="/console/status"))

    assert response.status_code == 303
    assert _location(response) == "/login?next=/console/status"


def test_console_page_renders_authenticated_layout_with_read_only_nav(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_READ_ONLY))
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)

    response = web.console_status(
        _Request(path="/console/status", cookies={dependencies.session_cookie_name(): service.token})
    )

    html = _body(response)
    assert response.status_code == 200
    assert "System Status" in html
    assert "Pete-Eebot" in html
    assert 'href="/console/plan"' in html
    assert 'href="/console/operations"' not in html
    assert 'href="/console/admin"' not in html


def test_operator_nav_shows_operator_page_but_hides_owner_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_OPERATOR))
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)

    response = web.console_plan(_Request(path="/console/plan", cookies={dependencies.session_cookie_name(): service.token}))

    html = _body(response)
    assert 'href="/console/operations"' in html
    assert 'href="/console/admin"' not in html


def test_owner_nav_shows_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_OWNER))
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)

    response = web.console_admin(_Request(path="/console/admin", cookies={dependencies.session_cookie_name(): service.token}))

    html = _body(response)
    assert response.status_code == 200
    assert "Owner access confirmed." in html
    assert 'href="/console/admin"' in html


def test_read_only_user_cannot_open_operator_page(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _UserService(_user(ROLE_READ_ONLY))
    monkeypatch.setattr(dependencies, "get_user_service", lambda: service)

    with pytest.raises(web.HTTPException) as exc:
        web.console_operations(
            _Request(path="/console/operations", cookies={dependencies.session_cookie_name(): service.token})
        )

    assert exc.value.status_code == 403


def test_web_routes_are_mounted_once_outside_api_v1_namespace() -> None:
    mounted_routes = {
        (method, route.path)
        for route in getattr(api.app, "routes", [])
        for method in getattr(route, "methods", set())
    }

    assert ("GET", "/console/status") in mounted_routes
    assert ("GET", "/login") in mounted_routes
    assert ("GET", f"{api.API_V1_PREFIX}/console/status") not in mounted_routes
