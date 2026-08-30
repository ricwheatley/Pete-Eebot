from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import Iterator

import pytest

from pete_e.infrastructure.wger_client import WgerClient, WgerError


_GENERATED_API_KEY = "-".join(("s01", "generated", "api", "key"))
_GENERATED_JWT = "-".join(("s01", "generated", "jwt"))


class _RecordingServer(ThreadingHTTPServer):
    redirect_status = 302
    redirect_target = ""

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.received: list[tuple[str, dict[str, str], bytes]] = []

    @property
    def origin(self) -> str:
        host, port = self.server_address
        return f"http://{host}:{port}"


class _Handler(BaseHTTPRequestHandler):
    server: _RecordingServer

    def do_GET(self) -> None:  # noqa: N802
        self._respond()

    def do_POST(self) -> None:  # noqa: N802
        self._respond()

    def log_message(self, format: str, *args: object) -> None:
        return None

    def _respond(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        self.server.received.append((self.path, dict(self.headers), body))

        if self.path == "/api/v2/ok/":
            payload = json.dumps({"ok": True}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        self.send_response(self.server.redirect_status)
        self.send_header("Location", f"{self.server.redirect_target}/collect")
        self.send_header("Content-Length", "0")
        self.end_headers()


@contextmanager
def _two_origins() -> Iterator[tuple[_RecordingServer, _RecordingServer]]:
    first = _RecordingServer()
    second = _RecordingServer()
    first.redirect_target = second.origin
    threads = [
        threading.Thread(target=first.serve_forever, daemon=True),
        threading.Thread(target=second.serve_forever, daemon=True),
    ]
    for thread in threads:
        thread.start()
    try:
        yield first, second
    finally:
        first.shutdown()
        second.shutdown()
        first.server_close()
        second.server_close()
        for thread in threads:
            thread.join(timeout=5)


def _settings(base_url: str, *, api_key: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        WGER_BASE_URL=base_url,
        WGER_API_KEY=api_key,
        WGER_USERNAME="s01-generated-user" if api_key is None else None,
        WGER_PASSWORD="s01-generated-password" if api_key is None else None,
        WGER_TIMEOUT=2.0,
        WGER_MAX_RETRIES=1,
        WGER_BACKOFF_BASE=0,
        DEBUG_API=False,
    )


@pytest.mark.contract
def test_real_requests_never_redirect_wger_credentials_to_another_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _two_origins() as (first, second):
        for status in range(300, 400):
            first.redirect_status = status

            monkeypatch.setattr(
                "pete_e.infrastructure.wger_client.settings",
                _settings(first.origin, api_key=_GENERATED_API_KEY),
            )
            with pytest.raises(
                WgerError, match="^Wger request redirects are not permitted\\.$"
            ):
                WgerClient()._request("GET", f"/redirect/{status}/api-key")

            monkeypatch.setattr(
                "pete_e.infrastructure.wger_client.settings",
                _settings(first.origin, api_key=None),
            )
            bearer_client = WgerClient()
            bearer_client._access_token = _GENERATED_JWT
            bearer_client._token_expiry = datetime.now(timezone.utc) + timedelta(
                minutes=1
            )
            with pytest.raises(
                WgerError, match="^Wger request redirects are not permitted\\.$"
            ):
                bearer_client._request("GET", f"/redirect/{status}/bearer")

            jwt_client = WgerClient()
            with pytest.raises(
                WgerError, match="^Wger request redirects are not permitted\\.$"
            ):
                jwt_client._get_jwt_token()

        assert len(first.received) == 300
        assert second.received == []
        assert all(
            "Authorization" in headers for _, headers, _ in first.received if not _
        )


@pytest.mark.contract
def test_real_same_origin_non_redirecting_request_still_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _two_origins() as (first, second):
        monkeypatch.setattr(
            "pete_e.infrastructure.wger_client.settings",
            _settings(first.origin, api_key=_GENERATED_API_KEY),
        )

        assert WgerClient()._request("GET", "/ok/") == {"ok": True}
        assert len(first.received) == 1
        assert "Authorization" in first.received[0][1]
        assert second.received == []
