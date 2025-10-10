from __future__ import annotations

from pete_e.infrastructure.wger_client import WgerClient


def test_set_config_posts_payload(monkeypatch):
    captured: dict[str, object] = {}

    def fake_request(self, method, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured["kwargs"] = kwargs
        return {}

    monkeypatch.setattr(WgerClient, "_request", fake_request)

    client = WgerClient()
    client.token = "token"  # ensure headers can be built

    client.set_config("sets", slot_entry_id=321, iteration=1, value=5)

    assert captured["method"] == "POST"
    assert captured["path"] == "/sets-config/"
    payload = captured["kwargs"]["json"]
    assert payload["slot_entry"] == 321
    assert payload["value"] == "5"
