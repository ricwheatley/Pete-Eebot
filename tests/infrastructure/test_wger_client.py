from __future__ import annotations

from types import SimpleNamespace

import pytest

from pete_e.infrastructure.wger_client import WgerClient


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

    monkeypatch.setattr(client, "_request", fake_request)

    detail = client.ping()

    assert detail == "wger.de (api-key)"
    assert calls == [("GET", "/routine/", {"params": {"limit": 1}})]
