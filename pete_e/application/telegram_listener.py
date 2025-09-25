"""Short-running Telegram command listener for Pete-Eebot."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Callable, Dict, Optional

from typing_extensions import Protocol

from pete_e.config import settings
from pete_e.infrastructure import log_utils, telegram_sender


class _LazyModuleProxy:
    """Provides attribute access to a module loaded only when required."""

    def __init__(self, module_name: str) -> None:
        object.__setattr__(self, "_module_name", module_name)
        object.__setattr__(self, "_module", None)

    def _load(self):
        module = object.__getattribute__(self, "_module")
        if module is None:
            module = importlib.import_module(object.__getattribute__(self, "_module_name"))
            object.__setattr__(self, "_module", module)
        return module

    def __getattribute__(self, item):
        if item in {"_module_name", "_module", "_load", "__dict__", "__class__", "__setattr__", "__getattribute__"}:
            return object.__getattribute__(self, item)

        data = object.__getattribute__(self, "__dict__")
        if item in data:
            return data[item]

        module = object.__getattribute__(self, "_load")()
        return getattr(module, item)

    def __setattr__(self, key, value):
        if key in {"_module_name", "_module"}:
            object.__setattr__(self, key, value)
        else:
            object.__getattribute__(self, "__dict__")[key] = value


messenger = _LazyModuleProxy("pete_e.cli.messenger")
messenger.build_daily_summary = None  # type: ignore[attr-defined]


class _OrchestratorProtocol(Protocol):
    def run_end_to_end_day(self, *, days: int = 1):
        ...

    def generate_strength_test_week(self) -> bool:
        ...


class TelegramCommandListener:
    """Polls Telegram once and routes supported bot commands."""

    def __init__(
        self,
        *,
        offset_path: Path | str | None = None,
        orchestrator_factory: Callable[[], _OrchestratorProtocol] | None = None,
        poll_limit: int = 5,
        poll_timeout: int = 2,
    ) -> None:
        self._offset_path = Path(offset_path) if offset_path else self._default_offset_path()
        self._offset_path.parent.mkdir(parents=True, exist_ok=True)
        self._orchestrator_factory = orchestrator_factory
        self._poll_limit = max(1, int(poll_limit))
        self._poll_timeout = max(0, int(poll_timeout))
        self._orchestrator: _OrchestratorProtocol | None = None

    @staticmethod
    def _default_offset_path() -> Path:
        history_path = settings.log_path
        return history_path.parent / "telegram_listener_offset.json"

    def _load_offset(self) -> Optional[int]:
        try:
            raw = self._offset_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        raw = raw.strip()
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            log_utils.log_message(
                f"Telegram listener offset file corrupt at {self._offset_path}; resetting.",
                "WARN",
            )
            return None
        value = data.get("last_update_id") if isinstance(data, dict) else None
        if isinstance(value, int):
            return value
        return None

    def _persist_offset(self, update_id: int) -> None:
        payload = {"last_update_id": int(update_id)}
        self._offset_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _next_offset(self) -> Optional[int]:
        last = self._load_offset()
        if last is None:
            return None
        return last + 1

    def _get_orchestrator(self) -> _OrchestratorProtocol:
        if self._orchestrator is not None:
            return self._orchestrator
        if self._orchestrator_factory is not None:
            self._orchestrator = self._orchestrator_factory()
            return self._orchestrator
        from pete_e.application.orchestrator import Orchestrator  # lazy import

        self._orchestrator = Orchestrator()
        return self._orchestrator

    def _handle_summary(self) -> str:
        build_summary = messenger.__dict__.get("build_daily_summary")
        if not callable(build_summary):
            build_summary = messenger.build_daily_summary

        summary = build_summary(orchestrator=self._get_orchestrator())
        summary_text = (summary or "").strip()
        if not summary_text:
            return "No summary is available yet."
        return summary_text

    def _handle_sync(self) -> str:
        try:
            result = self._get_orchestrator().run_end_to_end_day(days=1)
        except Exception as exc:  # pragma: no cover - defensive guardrail
            log_utils.log_message(f"Daily sync failed: {exc}", "ERROR")
            return "Daily sync failed; check logs."

        ingest_success = getattr(result, "ingest_success", False)
        summary_sent = getattr(result, "summary_sent", False)
        summary_attempted = getattr(result, "summary_attempted", False)
        failures = getattr(result, "failed_sources", None) or []

        failure_text = "none" if not failures else ", ".join(str(item) for item in failures)
        return (
            "Sync result: "
            f"ingest_success: {bool(ingest_success)} "
            f"summary_attempted: {bool(summary_attempted)} "
            f"summary_sent: {bool(summary_sent)} "
            f"failed_sources: {failure_text}"
        )

    def _handle_lets_begin(self) -> str:
        success = False
        try:
            result = self._get_orchestrator().generate_strength_test_week()
        except Exception as exc:  # pragma: no cover - defensive guardrail
            log_utils.log_message(
                f"Strength test week scheduling failed: {exc}",
                "ERROR",
            )
            success = False
        else:
            success = True if result is None else bool(result)

        if success:
            confirmation = "Strength test week scheduled"
            telegram_sender.send_alert(confirmation)
            return confirmation

        failure_message = "Strength test week scheduling failed; check logs."
        return failure_message

    def _extract_command(self, text: str) -> Optional[str]:
        stripped = text.strip()
        if not stripped.startswith("/"):
            return None
        head = stripped.split()[0]
        command = head.split("@", 1)[0]
        return command.lower()

    def listen_once(self) -> int:
        """Fetch a batch of updates, handle commands, and persist the offset."""

        next_offset = self._next_offset()
        updates = telegram_sender.get_updates(
            offset=next_offset,
            limit=self._poll_limit,
            timeout=self._poll_timeout,
        )

        if not updates:
            log_utils.log_message("Telegram listener polled no updates.", "DEBUG")
            return 0

        handled = 0
        max_update_id: Optional[int] = None
        handlers: Dict[str, Callable[[], str]] = {
            "/summary": self._handle_summary,
            "/sync": self._handle_sync,
            "/lets-begin": self._handle_lets_begin,
        }

        authorized_chat_id = getattr(settings, "TELEGRAM_CHAT_ID", None)

        for update in updates:
            update_id = update.get("update_id") if isinstance(update, dict) else None
            if isinstance(update_id, int):
                if max_update_id is None or update_id > max_update_id:
                    max_update_id = update_id

            message = update.get("message") if isinstance(update, dict) else None
            text = None
            if isinstance(message, dict):
                text = message.get("text")
                chat = message.get("chat")
            else:
                chat = None
            if not isinstance(text, str):
                continue

            chat_id = chat.get("id") if isinstance(chat, dict) else None
            if authorized_chat_id is not None and str(chat_id) != str(authorized_chat_id):
                log_utils.log_message(
                    "Skipping Telegram command from unauthorised chat.",
                    "WARN",
                )
                continue

            command = self._extract_command(text)
            if command not in handlers:
                continue

            try:
                response_text = handlers[command]()
            except Exception as exc:  # pragma: no cover - defensive guardrail
                log_utils.log_message(
                    f"Telegram command {command} failed: {exc}",
                    "ERROR",
                )
                response_text = "Command failed; check logs."

            escaped = telegram_sender.escape_markdown_v2(response_text)
            if not telegram_sender.send_message(escaped):
                log_utils.log_message(
                    f"Telegram listener failed to reply to {command}.",
                    "ERROR",
                )
            handled += 1

        if max_update_id is not None:
            self._persist_offset(max_update_id)

        return handled

