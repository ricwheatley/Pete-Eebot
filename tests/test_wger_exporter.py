from __future__ import annotations

from pete_e.infrastructure import wger_exporter


def test_set_sets_posts_string_payload(monkeypatch):
    captured: dict[str, object] = {}

    def fake_post(self, path, payload):  # type: ignore[override]
        captured["path"] = path
        captured["payload"] = payload
        return {}

    monkeypatch.setattr(wger_exporter.WgerClient, "post", fake_post, raising=False)

    client = wger_exporter.WgerClient(base_url="https://example.com", token="dummy-token")
    client.set_sets(slot_entry_id=321, sets=5)

    assert captured["path"] == "/api/v2/sets-config/"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["slot_entry"] == 321
    assert payload["value"] == "5"

