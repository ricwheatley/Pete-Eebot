"""Optional LLM voice rewrite layer for Pete's final messages."""

from __future__ import annotations

from typing import Mapping, Protocol, Sequence

from pete_e.infrastructure import log_utils

SYSTEM_PROMPT = (
    "You are Pete, Ric's direct but friendly fitness coach. Rewrite the draft into one natural "
    "Telegram message in Pete's voice. Return only the rewritten message. Do not include options, "
    "explanations, labels, preambles, or follow-up questions. Do not add, remove, or change facts, "
    "numbers, exercises, dates, targets, medical claims, readiness decisions, Wger status, or advice. "
    "Preserve important metrics, line breaks where useful, and Telegram-friendly formatting."
)


class CoachVoiceClient(Protocol):
    def chat(self, messages: Sequence[Mapping[str, str]]) -> str: ...


class CoachVoiceService:
    """Rewrite finalized coach messages when enabled, falling back on any issue."""

    def __init__(self, *, enabled: bool, client: CoachVoiceClient | None = None) -> None:
        self.enabled = enabled
        self.client = client

    def rewrite(self, draft_message: str) -> str:
        if not self.enabled or self.client is None or not draft_message.strip():
            return draft_message

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Rewrite this draft only:\n\n{draft_message}"},
        ]

        try:
            rewritten = self.client.chat(messages)
            if not isinstance(rewritten, str) or not rewritten.strip():
                raise ValueError("voice rewrite returned empty content")
            return rewritten
        except Exception as exc:
            log_utils.warn(f"Pete voice rewrite failed; using original message: {exc}")
            return draft_message
