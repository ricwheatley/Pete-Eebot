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


class StubTelegramClient:
    def __init__(self, *, updates: list[dict] | None = None) -> None:
        self.updates = updates or []
        self.sent_messages: list[str] = []
        self.alerts: list[str] = []
        self.get_updates_calls: list[dict[str, int | None]] = []
        self.send_result = True
        self.alert_result = True

    def get_updates(self, *, offset=None, limit, timeout):  # type: ignore[override]
        self.get_updates_calls.append({
            "offset": offset,
            "limit": limit,
            "timeout": timeout,
        })
        return list(self.updates)

    def send_message(self, message: str) -> bool:
        self.sent_messages.append(message)
        return self.send_result

    def send_alert(self, message: str) -> bool:
        self.alerts.append(message)
        return self.alert_result


def test_listen_once_handles_summary_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    updates = [_make_update(42, "/summary", chat_id=42)]
    client = StubTelegramClient(updates=updates)

    # Patch settings so this chat is authorised
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "42")

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
        telegram_client=client,
    )

    processed = listener.listen_once()

    assert processed == 1
    assert client.sent_messages == ["Daily summary ready"]
    stored = json.loads((tmp_path / "offset.json").read_text())
    assert stored["last_update_id"] == 42


def test_listen_once_runs_sync_and_reports_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    updates = [_make_update(77, "/sync", chat_id=77)]
    client = StubTelegramClient(updates=updates)

    # Patch settings so this chat is authorised
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "77")

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
        telegram_client=client,
    )

    processed = listener.listen_once()

    assert processed == 1
    assert len(client.sent_messages) == 1
    assert "Sync result" in client.sent_messages[0]
    assert "ingest_success: True" in client.sent_messages[0]
    assert "summary_sent: True" in client.sent_messages[0]
    stored = json.loads((tmp_path / "offset.json").read_text())
    assert stored["last_update_id"] == 77


def test_listen_once_triggers_strength_test_week(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    updates = [_make_update(99, "/lets-begin", chat_id=99)]
    client = StubTelegramClient(updates=updates)

    # Patch settings so this chat is authorised
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "99")
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
        telegram_client=client,
    )

    processed = listener.listen_once()

    assert processed == 1
    assert client.sent_messages == ["Strength test week scheduled"]
    assert client.alerts == ["Strength test week scheduled"]
    assert orchestration_calls == {"generate": 1}
    assert factory_calls == ["called"]
    stored = json.loads((tmp_path / "offset.json").read_text())
    assert stored["last_update_id"] == 99


def test_listen_once_uses_stored_offset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    offset_file = tmp_path / "offset.json"
    offset_file.write_text(json.dumps({"last_update_id": 900}))
    client = StubTelegramClient(updates=[])

    listener = TelegramCommandListener(
        offset_path=offset_file,
        poll_limit=4,
        poll_timeout=1,
        telegram_client=client,
    )

    processed = listener.listen_once()

    assert processed == 0
    assert client.get_updates_calls == [{"offset": 901, "limit": 4, "timeout": 1}]
    stored = json.loads(offset_file.read_text())
    assert stored["last_update_id"] == 900
