from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")

from pete_e.application import telegram_listener
from pete_e.application.telegram_listener import TelegramCommandListener
from pete_e.config import settings


def _make_update(update_id: int, text: str, chat_id: int = 123456) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "date": 1695270000,
            "chat": {"id": chat_id},
            "text": text,
        },
    }


def test_listen_once_handles_summary_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    updates = [_make_update(42, "/summary", chat_id=42)]
    captured: list[str] = []

    # Patch settings so this chat is authorised
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "42")

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
        telegram_listener,
        "messenger",
        SimpleNamespace(
            build_daily_summary=lambda orchestrator=None, target_date=None: "Daily summary ready"
        ),
    )

    listener = TelegramCommandListener(
        offset_path=tmp_path / "offset.json",
        poll_limit=5,
        poll_timeout=0,
        orchestrator_factory=lambda: SimpleNamespace(),
    )

    processed = listener.listen_once()

    assert processed == 1
    assert captured == ["Daily summary ready"]
    stored = json.loads((tmp_path / "offset.json").read_text())
    assert stored["last_update_id"] == 42


def test_listen_once_runs_sync_and_reports_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    updates = [_make_update(77, "/sync", chat_id=77)]
    captured: list[str] = []

    # Patch settings so this chat is authorised
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "77")

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
    assert "ingest_success: True" in captured[0]
    assert "summary_sent: True" in captured[0]
    stored = json.loads((tmp_path / "offset.json").read_text())
    assert stored["last_update_id"] == 77


def test_listen_once_triggers_strength_test_week(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    updates = [_make_update(99, "/lets-begin", chat_id=99)]
    captured: list[str] = []
    alerts: list[str] = []

    # Patch settings so this chat is authorised
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "99")

    monkeypatch.setattr(
        telegram_listener.telegram_sender,
        "get_updates",
        lambda *, offset=None, limit=2, timeout=0: updates,
    )

    def fake_send(message: str) -> bool:
        captured.append(message)
        return True

    monkeypatch.setattr(telegram_listener.telegram_sender, "send_message", fake_send)
    monkeypatch.setattr(
        telegram_listener.telegram_sender,
        "send_alert",
        lambda message: alerts.append(message) or True,
    )
    orchestration_calls: dict[str, int] = {"generate": 0}
    factory_calls: list[object] = []

    def fake_generate() -> None:
        orchestration_calls["generate"] += 1

    orch_stub = SimpleNamespace(generate_strength_test_week=fake_generate)

    listener = TelegramCommandListener(
        offset_path=tmp_path / "offset.json",
        poll_limit=2,
        poll_timeout=0,
        orchestrator_factory=lambda: factory_calls.append("called") or orch_stub,
    )

    processed = listener.listen_once()

    assert processed == 1
    assert captured == ["Strength test week scheduled"]
    assert alerts == ["Strength test week scheduled"]
    assert orchestration_calls == {"generate": 1}
    assert factory_calls == ["called"]
    stored = json.loads((tmp_path / "offset.json").read_text())
    assert stored["last_update_id"] == 99


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
