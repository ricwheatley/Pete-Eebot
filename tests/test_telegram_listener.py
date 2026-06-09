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
    """Perform make update."""


class StubTelegramClient:
    def __init__(self, *, updates: list[dict] | None = None) -> None:
        self.updates = updates or []
        self.sent_messages: list[str] = []
        self.alerts: list[str] = []
        self.get_updates_calls: list[dict[str, int | None]] = []
        self.send_result = True
        self.alert_result = True
        """Initialize this object."""

    def get_updates(self, *, offset=None, limit, timeout):  # type: ignore[override]
        self.get_updates_calls.append({
            "offset": offset,
            "limit": limit,
            "timeout": timeout,
        })
        return list(self.updates)
        """Perform get updates."""

    def send_message(self, message: str) -> bool:
        self.sent_messages.append(message)
        return self.send_result
        """Perform send message."""

    def send_alert(self, message: str) -> bool:
        self.alerts.append(message)
        return self.alert_result
        """Perform send alert."""
    """Represent StubTelegramClient."""


class OffsetAwareTelegramClient(StubTelegramClient):
    def get_updates(self, *, offset=None, limit, timeout):  # type: ignore[override]
        self.get_updates_calls.append({
            "offset": offset,
            "limit": limit,
            "timeout": timeout,
        })
        if offset is not None:
            return [update for update in self.updates if update.get("update_id", -1) >= offset]
        return list(self.updates)
        """Perform get updates."""
    """Represent OffsetAwareTelegramClient."""


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
    """Perform test listen once handles summary command."""


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
    """Perform test listen once runs sync and reports status."""


def test_listen_once_triggers_strength_test_week(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    updates = [_make_update(99, "/lets-begin", chat_id=99)]
    client = StubTelegramClient(updates=updates)

    # Patch settings so this chat is authorised
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "99")
    orchestration_calls: dict[str, int] = {"generate": 0}
    factory_calls: list[object] = []

    def fake_generate() -> None:
        orchestration_calls["generate"] += 1
        """Perform fake generate."""

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
    """Perform test listen once triggers strength test week."""


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
    """Perform test listen once uses stored offset."""


def test_summary_offset_is_persisted_before_slow_handler_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    offset_file = tmp_path / "offset.json"
    updates = [_make_update(501, "/summary", chat_id=42)]
    client = StubTelegramClient(updates=updates)
    observed: dict[str, int] = {}

    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "42")

    def slow_summary(orchestrator=None, target_date=None):
        observed["stored_before_handler"] = json.loads(offset_file.read_text())["last_update_id"]
        return "Daily summary ready"

    monkeypatch.setattr(
        telegram_listener,
        "messenger",
        SimpleNamespace(build_daily_summary=slow_summary),
    )

    listener = TelegramCommandListener(
        offset_path=offset_file,
        poll_limit=5,
        poll_timeout=0,
        orchestrator_factory=lambda: SimpleNamespace(),
        telegram_client=client,
    )

    processed = listener.listen_once()

    assert processed == 1
    assert observed == {"stored_before_handler": 501}
    assert client.sent_messages == ["Daily summary ready"]
    assert json.loads(offset_file.read_text())["last_update_id"] == 501
    """Perform test summary offset is persisted before slow handler runs."""


def test_second_listener_uses_advanced_offset_and_does_not_rehandle_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    offset_file = tmp_path / "offset.json"
    updates = [_make_update(502, "/summary", chat_id=42)]
    first_client = OffsetAwareTelegramClient(updates=updates)
    second_client = OffsetAwareTelegramClient(updates=updates)

    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "42")
    monkeypatch.setattr(
        telegram_listener,
        "messenger",
        SimpleNamespace(
            build_daily_summary=lambda orchestrator=None, target_date=None: "Daily summary ready"
        ),
    )

    first_listener = TelegramCommandListener(
        offset_path=offset_file,
        poll_limit=5,
        poll_timeout=0,
        orchestrator_factory=lambda: SimpleNamespace(),
        telegram_client=first_client,
    )
    second_listener = TelegramCommandListener(
        offset_path=offset_file,
        poll_limit=5,
        poll_timeout=0,
        orchestrator_factory=lambda: SimpleNamespace(),
        telegram_client=second_client,
    )

    assert first_listener.listen_once() == 1
    assert second_listener.listen_once() == 0

    assert first_client.sent_messages == ["Daily summary ready"]
    assert second_client.get_updates_calls == [{"offset": 503, "limit": 5, "timeout": 0}]
    assert second_client.sent_messages == []
    """Perform test second listener uses advanced offset and does not rehandle summary."""


def test_unauthorized_command_advances_offset_without_reply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    offset_file = tmp_path / "offset.json"
    updates = [_make_update(601, "/summary", chat_id=999)]
    client = StubTelegramClient(updates=updates)

    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "42")

    listener = TelegramCommandListener(
        offset_path=offset_file,
        poll_limit=5,
        poll_timeout=0,
        orchestrator_factory=lambda: SimpleNamespace(),
        telegram_client=client,
    )

    assert listener.listen_once() == 0
    assert client.sent_messages == []
    assert json.loads(offset_file.read_text())["last_update_id"] == 601
    """Perform test unauthorized command advances offset without reply."""


def test_non_command_update_advances_offset_without_reply(tmp_path: Path) -> None:
    offset_file = tmp_path / "offset.json"
    updates = [_make_update(602, "hello", chat_id=42)]
    client = StubTelegramClient(updates=updates)

    listener = TelegramCommandListener(
        offset_path=offset_file,
        poll_limit=5,
        poll_timeout=0,
        orchestrator_factory=lambda: SimpleNamespace(),
        telegram_client=client,
    )

    assert listener.listen_once() == 0
    assert client.sent_messages == []
    assert json.loads(offset_file.read_text())["last_update_id"] == 602
    """Perform test non command update advances offset without reply."""


def test_handler_exception_advances_offset_and_sends_failure_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    offset_file = tmp_path / "offset.json"
    updates = [_make_update(701, "/summary", chat_id=42)]
    client = StubTelegramClient(updates=updates)

    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "42")

    def failing_summary(orchestrator=None, target_date=None):
        assert json.loads(offset_file.read_text())["last_update_id"] == 701
        raise RuntimeError("slow summary failed")

    monkeypatch.setattr(
        telegram_listener,
        "messenger",
        SimpleNamespace(build_daily_summary=failing_summary),
    )

    listener = TelegramCommandListener(
        offset_path=offset_file,
        poll_limit=5,
        poll_timeout=0,
        orchestrator_factory=lambda: SimpleNamespace(),
        telegram_client=client,
    )

    assert listener.listen_once() == 1
    assert client.sent_messages == ["Command failed; check logs."]
    assert json.loads(offset_file.read_text())["last_update_id"] == 701
    """Perform test handler exception advances offset and sends failure response."""


def test_send_failure_does_not_leave_update_reprocessable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    offset_file = tmp_path / "offset.json"
    updates = [_make_update(801, "/summary", chat_id=42)]
    first_client = OffsetAwareTelegramClient(updates=updates)
    first_client.send_result = False
    second_client = OffsetAwareTelegramClient(updates=updates)

    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "42")
    monkeypatch.setattr(
        telegram_listener,
        "messenger",
        SimpleNamespace(
            build_daily_summary=lambda orchestrator=None, target_date=None: "Daily summary ready"
        ),
    )

    first_listener = TelegramCommandListener(
        offset_path=offset_file,
        poll_limit=5,
        poll_timeout=0,
        orchestrator_factory=lambda: SimpleNamespace(),
        telegram_client=first_client,
    )
    second_listener = TelegramCommandListener(
        offset_path=offset_file,
        poll_limit=5,
        poll_timeout=0,
        orchestrator_factory=lambda: SimpleNamespace(),
        telegram_client=second_client,
    )

    assert first_listener.listen_once() == 1
    assert second_listener.listen_once() == 0
    assert first_client.sent_messages == ["Daily summary ready"]
    assert second_client.sent_messages == []
    assert second_client.get_updates_calls == [{"offset": 802, "limit": 5, "timeout": 0}]
    """Perform test send failure does not leave update reprocessable."""


def test_existing_listener_lock_skips_poll(tmp_path: Path) -> None:
    offset_file = tmp_path / "offset.json"
    lock_file = tmp_path / "offset.json.lock"
    lock_file.write_text("other-process\n", encoding="utf-8")
    client = StubTelegramClient(updates=[_make_update(901, "/summary", chat_id=42)])

    listener = TelegramCommandListener(
        offset_path=offset_file,
        poll_limit=5,
        poll_timeout=0,
        telegram_client=client,
    )

    assert listener.listen_once() == 0
    assert client.get_updates_calls == []
    assert lock_file.exists()
    """Perform test existing listener lock skips poll."""
