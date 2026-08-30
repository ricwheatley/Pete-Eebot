from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from pete_e.infrastructure.wger_client import WgerClient, WgerError


_GENERATED_API_KEY = "-".join(("s01", "generated", "api", "key"))
_GENERATED_JWT = "-".join(("s01", "generated", "jwt"))


def test_get_workout_logs_uses_inclusive_local_date_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pete_e.infrastructure.wger_client.settings",
        SimpleNamespace(
            WGER_BASE_URL="https://wger.de/api/v2",
            WGER_API_KEY="dummy-key",
            WGER_USERNAME=None,
            WGER_PASSWORD=None,
            WGER_TIMEOUT=5.0,
            WGER_MAX_RETRIES=3,
            WGER_BACKOFF_BASE=0.5,
            USER_TIMEZONE="Europe/London",
            DEBUG_API=False,
        ),
    )
    client = WgerClient(timeout=2.5)
    calls: list[tuple[str, dict]] = []

    def fake_get_all_pages(path: str, params=None):
        calls.append((path, dict(params or {})))
        return []

    monkeypatch.setattr(client, "get_all_pages", fake_get_all_pages)

    assert client.get_workout_logs(date(2026, 8, 17), date(2026, 8, 23)) == []
    assert calls == [
        (
            "/workoutlog/",
            {
                "ordering": "date,id",
                "limit": 200,
                "date__gte": "2026-08-16T23:00:00+00:00",
                "date__lt": "2026-08-23T23:00:00+00:00",
            },
        )
    ]


def test_ping_checks_authenticated_endpoint_and_reports_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pete_e.infrastructure.wger_client.settings",
        SimpleNamespace(
            WGER_BASE_URL="https://wger.de/api/v2",
            WGER_API_KEY="dummy-key",
            WGER_USERNAME=None,
            WGER_PASSWORD=None,
            WGER_TIMEOUT=5.0,
            WGER_MAX_RETRIES=3,
            WGER_BACKOFF_BASE=0.5,
            DEBUG_API=False,
        ),
    )

    client = WgerClient(timeout=2.5)
    calls: list[tuple[str, str, dict]] = []

    def fake_request(method: str, path: str, **kwargs):
        calls.append((method, path, kwargs))
        return {"results": []}
        """Perform fake request."""

    monkeypatch.setattr(client, "_request", fake_request)

    detail = client.ping()

    assert detail == "wger.de (api-key)"
    assert calls == [("GET", "/routine/", {"params": {"limit": 1}})]
    """Perform test ping checks authenticated endpoint and reports host."""


def test_delete_all_days_ignores_stale_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pete_e.infrastructure.wger_client.settings",
        SimpleNamespace(
            WGER_BASE_URL="https://wger.de/api/v2",
            WGER_API_KEY="dummy-key",
            WGER_USERNAME=None,
            WGER_PASSWORD=None,
            WGER_TIMEOUT=5.0,
            WGER_MAX_RETRIES=3,
            WGER_BACKOFF_BASE=0.5,
            DEBUG_API=False,
        ),
    )
    warnings: list[str] = []
    monkeypatch.setattr("pete_e.infrastructure.wger_client.log_utils.warn", warnings.append)

    client = WgerClient(timeout=2.5)
    monkeypatch.setattr(
        client,
        "get_all_pages",
        lambda path, params=None: [{"id": 111}, {"id": 222}],
    )

    deleted: list[str] = []

    def fake_request(method: str, path: str, **kwargs):
        deleted.append(path)
        if path == "/day/111/":
            response = SimpleNamespace(status_code=404, text='{"detail":"Not found."}')
            raise WgerError("DELETE /day/111/ failed with 404", response)
        return None
        """Perform fake request."""

    monkeypatch.setattr(client, "_request", fake_request)

    client.delete_all_days_in_routine(42)

    assert deleted == ["/day/111/", "/day/222/"]
    assert warnings == ["Skipping stale wger day 111 for routine 42: already deleted."]
    """Perform test delete all days ignores stale 404."""


def test_find_routine_returns_only_an_exact_name_and_start_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pete_e.infrastructure.wger_client.settings",
        SimpleNamespace(
            WGER_BASE_URL="https://wger.de/api/v2",
            WGER_API_KEY="dummy-key",
            WGER_USERNAME=None,
            WGER_PASSWORD=None,
            WGER_TIMEOUT=5.0,
            WGER_MAX_RETRIES=3,
            WGER_BACKOFF_BASE=0.5,
            DEBUG_API=False,
        ),
    )
    client = WgerClient(timeout=2.5)
    calls: list[tuple[str, str, dict]] = []

    def fake_request(method: str, path: str, **kwargs):
        calls.append((method, path, kwargs))
        return {
            "results": [
                {"id": 1, "name": "Pete-E Week 2026-08-17", "start": "2026-08-24"},
                {"id": 2, "name": "Pete-E Week 2026-08-24", "start": "2026-08-17"},
                {"id": 3, "name": "Pete-E Week 2026-08-24", "start": "2026-08-24"},
            ]
        }

    monkeypatch.setattr(client, "_request", fake_request)

    routine = client.find_routine("Pete-E Week 2026-08-24", date(2026, 8, 24))

    assert routine == {
        "id": 3,
        "name": "Pete-E Week 2026-08-24",
        "start": "2026-08-24",
    }
    assert calls == [
        (
            "GET",
            "/routine/",
            {"params": {"name": "Pete-E Week 2026-08-24", "start": "2026-08-24"}},
        )
    ]


def test_ensure_custom_exercise_reuses_existing_translation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pete_e.infrastructure.wger_client.settings",
        SimpleNamespace(
            WGER_BASE_URL="https://wger.de/api/v2",
            WGER_API_KEY="dummy-key",
            WGER_USERNAME=None,
            WGER_PASSWORD=None,
            WGER_TIMEOUT=5.0,
            WGER_MAX_RETRIES=3,
            WGER_BACKOFF_BASE=0.5,
            DEBUG_API=False,
        ),
    )

    client = WgerClient(timeout=2.5)
    calls: list[tuple[str, str, dict]] = []

    def fake_request(method: str, path: str, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET":
            return {
                "results": [
                    {
                        "id": 3100,
                        "name": "Limber 11",
                        "language": 2,
                        "exercise": 1949,
                        "description": "11-step mobility flow",
                    },
                ]
            }
        raise AssertionError("unexpected write call")
        """Perform fake request."""

    monkeypatch.setattr(client, "_request", fake_request)

    exercise_id = client.ensure_custom_exercise(
        name="Limber 11",
        description="11-step mobility flow",
    )

    assert exercise_id == 1949
    assert calls == [
        ("GET", "/exercise-translation/", {"params": {"name": "Limber 11", "language": 2}})
    ]
    """Perform test ensure custom exercise reuses existing translation."""


def test_ensure_custom_exercise_updates_existing_translation_when_description_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pete_e.infrastructure.wger_client.settings",
        SimpleNamespace(
            WGER_BASE_URL="https://wger.de/api/v2",
            WGER_API_KEY="dummy-key",
            WGER_USERNAME=None,
            WGER_PASSWORD=None,
            WGER_TIMEOUT=5.0,
            WGER_MAX_RETRIES=3,
            WGER_BACKOFF_BASE=0.5,
            DEBUG_API=False,
        ),
    )

    client = WgerClient(timeout=2.5)
    calls: list[tuple[str, str, dict]] = []

    def fake_request(method: str, path: str, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET":
            return {
                "results": [
                    {
                        "id": 3100,
                        "name": "Limber 11",
                        "language": 2,
                        "exercise": 1949,
                        "description": "old description",
                    }
                ]
            }
        if method == "PATCH":
            return {"id": 3100}
        raise AssertionError(f"unexpected call {method} {path}")
        """Perform fake request."""

    monkeypatch.setattr(client, "_request", fake_request)

    exercise_id = client.ensure_custom_exercise(
        name="Limber 11",
        description="new description",
    )

    assert exercise_id == 1949
    assert calls == [
        ("GET", "/exercise-translation/", {"params": {"name": "Limber 11", "language": 2}}),
        (
            "PATCH",
            "/exercise-translation/3100/",
            {
                "json": {
                    "name": "Limber 11",
                    "exercise": 1949,
                    "description": "new description",
                    "language": 2,
                    "license_author": "Pete-E automation",
                }
            },
        ),
    ]
    """Perform test ensure custom exercise updates existing translation when description changes."""


def test_ensure_custom_exercise_creates_exercise_and_translation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pete_e.infrastructure.wger_client.settings",
        SimpleNamespace(
            WGER_BASE_URL="https://wger.de/api/v2",
            WGER_API_KEY="dummy-key",
            WGER_USERNAME=None,
            WGER_PASSWORD=None,
            WGER_TIMEOUT=5.0,
            WGER_MAX_RETRIES=3,
            WGER_BACKOFF_BASE=0.5,
            DEBUG_API=False,
        ),
    )

    client = WgerClient(timeout=2.5)
    calls: list[tuple[str, str, dict]] = []

    def fake_request(method: str, path: str, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET":
            return {"results": []}
        if method == "POST" and path == "/exercise/":
            return {"id": 2501}
        if method == "POST" and path == "/exercise-translation/":
            return {"id": 9001}
        raise AssertionError(f"unexpected call {method} {path}")
        """Perform fake request."""

    monkeypatch.setattr(client, "_request", fake_request)

    exercise_id = client.ensure_custom_exercise(
        name="Limber 11",
        description="11-step mobility flow",
    )

    assert exercise_id == 2501
    assert calls == [
        ("GET", "/exercise-translation/", {"params": {"name": "Limber 11", "language": 2}}),
        (
            "POST",
            "/exercise/",
            {
                "json": {
                    "category": 9,
                    "muscles": [],
                    "muscles_secondary": [],
                    "equipment": [],
                    "license_author": "Pete-E automation",
                }
            },
        ),
        (
            "POST",
            "/exercise-translation/",
            {
                "json": {
                    "name": "Limber 11",
                    "exercise": 2501,
                    "description": "11-step mobility flow",
                    "language": 2,
                    "license_author": "Pete-E automation",
                }
            },
        ),
    ]
    """Perform test ensure custom exercise creates exercise and translation."""


def test_pagination_rejects_cross_origin_before_reusing_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Characterize the credential-bearing cross-origin pagination boundary."""

    monkeypatch.setattr(
        "pete_e.infrastructure.wger_client.settings",
        SimpleNamespace(
            WGER_BASE_URL="https://wger.de/api/v2",
            WGER_API_KEY=_GENERATED_API_KEY,
            WGER_USERNAME=None,
            WGER_PASSWORD=None,
            WGER_TIMEOUT=5.0,
            WGER_MAX_RETRIES=1,
            WGER_BACKOFF_BASE=0,
            DEBUG_API=False,
        ),
    )
    calls = 0

    def fake_request(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return SimpleNamespace(
                status_code=200,
                text="",
                json=lambda: {
                    "results": [{"id": 1}],
                    "next": "https://pagination.invalid/collect",
                },
            )
        assert kwargs["url"].startswith("https://pagination.invalid/")
        assert "Authorization" in kwargs["headers"]
        return SimpleNamespace(
            status_code=200,
            text="",
            json=lambda: {"results": [], "next": None},
        )

    monkeypatch.setattr("pete_e.infrastructure.wger_client.requests.request", fake_request)

    with pytest.raises(WgerError, match="Rejected Wger URL outside the configured origin"):
        WgerClient().get_all_pages("/exerciseinfo/")

    assert calls == 1


def _security_settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "WGER_BASE_URL": "https://wger.de/api/v2",
        "WGER_API_KEY": _GENERATED_API_KEY,
        "WGER_USERNAME": None,
        "WGER_PASSWORD": None,
        "WGER_TIMEOUT": 5.0,
        "WGER_MAX_RETRIES": 1,
        "WGER_BACKOFF_BASE": 0,
        "DEBUG_API": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    "base_url",
    [
        "file:///tmp/wger",
        "wger.invalid/api/v2",
        "https://user:password@wger.invalid/api/v2",
        "https://wger.invalid/api/v2?unsafe=1",
        "https://wger.invalid/api/v2#unsafe",
    ],
)
def test_invalid_base_fails_before_authentication_or_network(
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
) -> None:
    monkeypatch.setattr(
        "pete_e.infrastructure.wger_client.settings",
        _security_settings(WGER_BASE_URL=base_url),
    )
    request_calls = 0

    def unexpected_request(**kwargs: object) -> None:
        nonlocal request_calls
        request_calls += 1

    monkeypatch.setattr("pete_e.infrastructure.wger_client.requests.request", unexpected_request)

    with pytest.raises(WgerError) as captured:
        WgerClient()

    assert str(captured.value).startswith("WGER_BASE_URL must be an absolute HTTP(S) URL")
    assert base_url not in str(captured.value)
    assert request_calls == 0


@pytest.mark.parametrize(
    ("target", "message"),
    [
        (
            "https://pagination.invalid/collect",
            "Rejected Wger URL outside the configured origin.",
        ),
        (
            "https://user:password@wger.de/api/v2/collect",
            "Wger pagination returned an invalid next URL.",
        ),
        (
            "https://wger.de/api/v2/collect#fragment",
            "Wger pagination returned an invalid next URL.",
        ),
    ],
)
def test_rejected_initial_target_never_builds_jwt_headers_or_logs_the_url(
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    message: str,
) -> None:
    monkeypatch.setattr(
        "pete_e.infrastructure.wger_client.settings",
        _security_settings(
            WGER_API_KEY=None,
            WGER_USERNAME="s01-generated-user",
            WGER_PASSWORD="s01-generated-password",
            DEBUG_API=True,
        ),
    )
    client = WgerClient()
    jwt_calls = 0
    request_calls = 0
    debug_messages: list[str] = []

    def unexpected_jwt() -> str:
        nonlocal jwt_calls
        jwt_calls += 1
        return _GENERATED_JWT

    def unexpected_request(**kwargs: object) -> None:
        nonlocal request_calls
        request_calls += 1

    monkeypatch.setattr(client, "_get_jwt_token", unexpected_jwt)
    monkeypatch.setattr("pete_e.infrastructure.wger_client.requests.request", unexpected_request)
    monkeypatch.setattr("pete_e.infrastructure.wger_client.log_utils.debug", debug_messages.append)

    with pytest.raises(WgerError) as captured:
        client._request("GET", target)

    assert str(captured.value) == message
    assert target not in str(captured.value)
    assert jwt_calls == 0
    assert request_calls == 0
    assert debug_messages == []


def test_pagination_preserves_order_duplicates_and_first_request_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pete_e.infrastructure.wger_client.settings",
        _security_settings(WGER_BASE_URL="https://fitness.example/wger/api/v2"),
    )
    client = WgerClient()
    calls: list[tuple[str, dict[str, object]]] = []
    pages = [
        {
            "results": [{"id": 1}, {"id": 1}],
            "next": "?limit=2&offset=2",
        },
        {"results": [{"id": 2}], "next": "/wger/api/v2/items/?limit=2&offset=4"},
        {"results": [{"id": 3}], "next": None},
    ]

    def fake_request(method: str, path: str, **kwargs: object) -> object:
        assert method == "GET"
        calls.append((path, kwargs["params"]))  # type: ignore[arg-type]
        return pages[len(calls) - 1]

    monkeypatch.setattr(client, "_request", fake_request)

    assert client.get_all_pages("items/", params={"limit": 2, "offset": 0}) == [
        {"id": 1},
        {"id": 1},
        {"id": 2},
        {"id": 3},
    ]
    assert calls == [
        ("https://fitness.example/wger/api/v2/items/", {"limit": 2, "offset": 0}),
        ("https://fitness.example/wger/api/v2/items/?limit=2&offset=2", {}),
        ("https://fitness.example/wger/api/v2/items/?limit=2&offset=4", {}),
    ]


@pytest.mark.parametrize("next_value", [1, [], {}])
def test_non_string_next_fails_without_a_second_request(
    monkeypatch: pytest.MonkeyPatch,
    next_value: object,
) -> None:
    monkeypatch.setattr("pete_e.infrastructure.wger_client.settings", _security_settings())
    client = WgerClient()
    calls = 0

    def fake_request(method: str, path: str, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return {"results": [], "next": next_value}

    monkeypatch.setattr(client, "_request", fake_request)

    with pytest.raises(WgerError, match="^Wger pagination returned an invalid next URL\\.$"):
        client.get_all_pages("/items/")
    assert calls == 1


def test_pagination_cycle_is_detected_before_repeating_a_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pete_e.infrastructure.wger_client.settings", _security_settings())
    client = WgerClient()
    calls = 0

    def fake_request(method: str, path: str, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return {
            "results": [],
            "next": "https://wger.de/api/v2/items/?limit=1",
        }

    monkeypatch.setattr(client, "_request", fake_request)

    with pytest.raises(WgerError, match="^Wger pagination cycle detected\\.$"):
        client.get_all_pages("/items/", params={"limit": 1})
    assert calls == 1


def test_pagination_never_requests_page_1001(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pete_e.infrastructure.wger_client.settings", _security_settings())
    client = WgerClient()
    calls = 0

    def fake_request(method: str, path: str, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return {"results": [], "next": f"?page={calls}"}

    monkeypatch.setattr(client, "_request", fake_request)

    with pytest.raises(WgerError, match="^Wger pagination exceeded the 1000-page limit\\.$"):
        client.get_all_pages("/items/")
    assert calls == 1000


def test_request_disables_redirects_and_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pete_e.infrastructure.wger_client.settings", _security_settings())
    captured: dict[str, object] = {}

    def fake_request(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(status_code=302, text="")

    monkeypatch.setattr("pete_e.infrastructure.wger_client.requests.request", fake_request)

    with pytest.raises(WgerError, match="^Wger request redirects are not permitted\\.$"):
        WgerClient()._request("GET", "/items/")

    assert captured["allow_redirects"] is False
    assert "Authorization" in captured["headers"]  # type: ignore[operator]


def test_jwt_acquisition_disables_redirects_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pete_e.infrastructure.wger_client.settings",
        _security_settings(
            WGER_API_KEY=None,
            WGER_USERNAME="s01-generated-user",
            WGER_PASSWORD="s01-generated-password",
        ),
    )
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(status_code=307, text="")

    monkeypatch.setattr("pete_e.infrastructure.wger_client.requests.post", fake_post)

    with pytest.raises(WgerError, match="^Wger request redirects are not permitted\\.$"):
        WgerClient()._get_jwt_token()

    assert captured["allow_redirects"] is False
    assert set(captured["data"]) == {"username", "password"}  # type: ignore[arg-type]


def test_api_key_remains_preferred_over_jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pete_e.infrastructure.wger_client.settings",
        _security_settings(
            WGER_USERNAME="s01-generated-user",
            WGER_PASSWORD="s01-generated-password",
        ),
    )
    client = WgerClient()
    jwt_calls = 0

    def unexpected_jwt() -> str:
        nonlocal jwt_calls
        jwt_calls += 1
        return _GENERATED_JWT

    monkeypatch.setattr(client, "_get_jwt_token", unexpected_jwt)

    assert client._headers()["Authorization"].startswith("Token ")
    assert jwt_calls == 0
