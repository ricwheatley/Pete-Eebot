from __future__ import annotations

from pete_e.infrastructure.wger_client import WgerClient


def test_wger_client_retry_logic():
    client = WgerClient()
    retryable = [408, 429, 500, 502, 503, 504]
    assert all(client._should_retry(code) for code in retryable)  # type: ignore[attr-defined]
    assert client._should_retry(404) is False  # type: ignore[attr-defined]
