from __future__ import annotations

from datetime import date

from pete_e.infrastructure.wger_client import WgerClient


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

    assert client.create_routine("staging", "desc", start, end) == {"id": 44}
    assert client.update_routine(
        44,
        name="canonical",
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
                    "name": "staging",
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
                    "name": "canonical",
                    "description": "desc",
                    "start": "2026-08-24",
                    "end": "2026-08-30",
                }
            },
        ),
        ("DELETE", "/routine/44/", {}),
    ]
