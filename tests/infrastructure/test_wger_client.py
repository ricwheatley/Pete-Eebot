from __future__ import annotations

from types import SimpleNamespace

import pytest

from pete_e.infrastructure.wger_client import WgerClient, WgerError


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
