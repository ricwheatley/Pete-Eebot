from __future__ import annotations

from datetime import date

import pytest

from pete_e.infrastructure.wger_client import (
    WGER_ROUTINE_NAME_MAX_LENGTH,
    WgerClient,
    WgerError,
)


def test_set_config_posts_payload(monkeypatch):
    captured: dict[str, object] = {}

    def fake_request(self, method, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured["kwargs"] = kwargs
        return {}
        """Perform fake request."""

    monkeypatch.setattr(WgerClient, "_request", fake_request)

    client = WgerClient()
    client.token = "token"  # ensure headers can be built

    client.set_config("sets", slot_entry_id=321, iteration=1, value=5)

    assert captured["method"] == "POST"
    assert captured["path"] == "/sets-config/"
    payload = captured["kwargs"]["json"]
    assert payload["slot_entry"] == 321
    assert payload["value"] == 5
    """Perform test set config posts payload."""


def test_set_config_posts_weight_payload(monkeypatch):
    captured: dict[str, object] = {}

    def fake_request(self, method, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured["kwargs"] = kwargs
        return {}
        """Perform fake request."""

    monkeypatch.setattr(WgerClient, "_request", fake_request)

    client = WgerClient()
    client.token = "token"

    client.set_config("weight", slot_entry_id=654, iteration=1, value=47.5)

    assert captured["method"] == "POST"
    assert captured["path"] == "/weight-config/"
    payload = captured["kwargs"]["json"]
    assert payload["slot_entry"] == 654
    assert payload["value"] == "47.5"
    """Perform test set config posts weight payload."""


def test_set_config_posts_rest_payload(monkeypatch):
    captured: dict[str, object] = {}

    def fake_request(self, method, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured["kwargs"] = kwargs
        return {}
        """Perform fake request."""

    monkeypatch.setattr(WgerClient, "_request", fake_request)

    client = WgerClient()
    client.token = "token"

    client.set_config("rest", slot_entry_id=987, iteration=1, value=150)

    assert captured["method"] == "POST"
    assert captured["path"] == "/rest-config/"
    payload = captured["kwargs"]["json"]
    assert payload["slot_entry"] == 987
    assert payload["value"] == 150
    """Perform test set config posts rest payload."""


def test_routine_lifecycle_methods_use_canonical_api_resources(monkeypatch):
    captured: list[tuple[str, str, dict[str, object]]] = []

    def fake_request(self, method, path, **kwargs):
        captured.append((method, path, kwargs))
        return {"id": 44}

    monkeypatch.setattr(WgerClient, "_request", fake_request)
    client = WgerClient()
    start = date(2026, 8, 24)
    end = date(2026, 8, 30)
    create_name = "s" * WGER_ROUTINE_NAME_MAX_LENGTH
    update_name = "c" * WGER_ROUTINE_NAME_MAX_LENGTH

    assert client.create_routine(create_name, "desc", start, end) == {"id": 44}
    assert client.update_routine(
        44,
        name=update_name,
        description="desc",
        start=start,
        end=end,
    ) == {"id": 44}
    client.delete_routine(44)

    assert captured == [
        (
            "POST",
            "/routine/",
            {
                "json": {
                    "name": create_name,
                    "description": "desc",
                    "start": "2026-08-24",
                    "end": "2026-08-30",
                }
            },
        ),
        (
            "PATCH",
            "/routine/44/",
            {
                "json": {
                    "name": update_name,
                    "description": "desc",
                    "start": "2026-08-24",
                    "end": "2026-08-30",
                }
            },
        ),
        ("DELETE", "/routine/44/", {}),
    ]


def test_routine_writes_reject_overlong_names_before_request(monkeypatch):
    calls: list[object] = []

    monkeypatch.setattr(
        WgerClient,
        "_request",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    client = WgerClient()
    start = date(2026, 8, 24)
    overlong_name = "x" * (WGER_ROUTINE_NAME_MAX_LENGTH + 1)

    with pytest.raises(WgerError, match="25 characters or fewer; got 26"):
        client.create_routine(overlong_name, "desc", start, start)
    with pytest.raises(WgerError, match="25 characters or fewer; got 26"):
        client.update_routine(
            44,
            name=overlong_name,
            description="desc",
            start=start,
            end=start,
        )

    assert calls == []
