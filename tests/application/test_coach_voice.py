from __future__ import annotations

from typing import Mapping, Sequence

from pete_e.application.coach_voice import CoachVoiceService, SYSTEM_PROMPT


class _FakeClient:
    def __init__(self, response: str | None = None, exc: Exception | None = None) -> None:
        self.response = response
        self.exc = exc
        self.messages: Sequence[Mapping[str, str]] | None = None
        self.model = "qwen2.5:1.5b"

    def chat(self, messages: Sequence[Mapping[str, str]]) -> str:
        self.messages = messages
        if self.exc is not None:
            raise self.exc
        return self.response or ""


def test_llm_disabled_returns_original_message_unchanged() -> None:
    client = _FakeClient(response="rewritten")
    service = CoachVoiceService(enabled=False, client=client)

    assert service.rewrite("original draft") == "original draft"
    assert client.messages is None


def test_llm_enabled_fake_client_success_returns_rewritten_message(monkeypatch) -> None:
    logs: list[str] = []
    monkeypatch.setattr("pete_e.application.coach_voice.log_utils.info", logs.append)
    client = _FakeClient(response="rewritten message")
    service = CoachVoiceService(enabled=True, client=client)

    assert service.rewrite("original draft") == "rewritten message"
    assert client.messages is not None
    assert client.messages[0]["role"] == "system"
    assert client.messages[0]["content"] == SYSTEM_PROMPT
    assert "original draft" in client.messages[1]["content"]
    assert len(logs) == 1
    assert logs[0].startswith("Pete voice rewrite succeeded model=qwen2.5:1.5b duration_ms=")
    assert "original draft" not in logs[0]
    assert "rewritten message" not in logs[0]


def test_llm_enabled_fake_client_failure_returns_original_message(monkeypatch) -> None:
    warnings: list[str] = []
    monkeypatch.setattr("pete_e.application.coach_voice.log_utils.warn", warnings.append)
    service = CoachVoiceService(enabled=True, client=_FakeClient(exc=RuntimeError("boom")))

    assert service.rewrite("original draft") == "original draft"
    assert warnings == ["Pete voice rewrite failed; using original message: boom"]
    assert "original draft" not in warnings[0]


def test_llm_enabled_empty_client_response_returns_original_message(monkeypatch) -> None:
    warnings: list[str] = []
    monkeypatch.setattr("pete_e.application.coach_voice.log_utils.warn", warnings.append)
    service = CoachVoiceService(enabled=True, client=_FakeClient(response="   "))

    assert service.rewrite("original draft") == "original draft"
    assert warnings
