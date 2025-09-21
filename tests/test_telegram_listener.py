from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from pete_e.application import telegram_listener
from pete_e.application.telegram_listener import TelegramCommandListener


def _make_update(update_id: int, text: str) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "date": 1695270000,
            "chat": {"id": 123456},
            "text": text,
        },
    }


def test_listen_once_handles_summary_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    updates = [_make_update(42, "/summary")]
    captured: list[str] = []

    monkeypatch.setattr(
        telegram_listener.telegram_sender,
        "get_updates",
        lambda *, offset=None, limit=5, timeout=0: updates,
    )

    def fake_send(message: str) -> bool:
        captured.append(message)
        return True

    monkeypatch.setattr(telegram_listener.telegram_sender, "send_message", fake_send)
    monkeypatch.setattr(
        telegram_listener.messenger,
        "build_daily_summary",
        lambda orchestrator=None, target_date=None: "Daily summary ready",
    )

    listener = TelegramCommandListener(
        offset_path=tmp_path / "offset.json",
        poll_limit=5,
        poll_timeout=0,
    )

    processed = listener.listen_once()

    assert processed == 1
    assert captured == ["Daily summary ready"]
    stored = json.loads((tmp_path / "offset.json").read_text())
    assert stored["last_update_id"] == 42


def test_listen_once_runs_sync_and_reports_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    updates = [_make_update(77, "/sync")]
    captured: list[str] = []

    monkeypatch.setattr(
        telegram_listener.telegram_sender,
        "get_updates",
        lambda *, offset=None, limit=3, timeout=0: updates,
    )

    def fake_send(message: str) -> bool:
        captured.append(message)
        return True

    monkeypatch.setattr(telegram_listener.telegram_sender, "send_message", fake_send)

    result = SimpleNamespace(
        ingest_success=True,
        failed_sources=[],
        source_statuses={"AppleDropbox": "ok"},
        summary_target=date(2025, 9, 20),
        summary_sent=True,
        summary_attempted=True,
    )

    orch_stub = SimpleNamespace(run_end_to_end_day=lambda days=1: result)

    listener = TelegramCommandListener(
        offset_path=tmp_path / "offset.json",
        poll_limit=3,
        poll_timeout=0,
        orchestrator_factory=lambda: orch_stub,
    )

    processed = listener.listen_once()

    assert processed == 1
    assert len(captured) == 1
    assert "Sync result" in captured[0]
    assert "ingest\\_success: True" in captured[0]
    assert "summary\\_sent: True" in captured[0]
    stored = json.loads((tmp_path / "offset.json").read_text())
    assert stored["last_update_id"] == 77


def test_listen_once_uses_stored_offset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    offset_file = tmp_path / "offset.json"
    offset_file.write_text(json.dumps({"last_update_id": 900}))
    called = {}

    def fake_get_updates(*, offset=None, limit, timeout):
        called["offset"] = offset
        called["limit"] = limit
        called["timeout"] = timeout
        return []

    monkeypatch.setattr(
        telegram_listener.telegram_sender,
        "get_updates",
        fake_get_updates,
    )

    monkeypatch.setattr(telegram_listener.telegram_sender, "send_message", lambda message: True)

    listener = TelegramCommandListener(
        offset_path=offset_file,
        poll_limit=4,
        poll_timeout=1,
    )

    processed = listener.listen_once()

    assert processed == 0
    assert called == {"offset": 901, "limit": 4, "timeout": 1}
    stored = json.loads(offset_file.read_text())
    assert stored["last_update_id"] == 900


