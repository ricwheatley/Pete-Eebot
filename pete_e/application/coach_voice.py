"""Optional LLM voice rewrite layer for Pete's final messages."""

from __future__ import annotations

from time import perf_counter
from typing import Mapping, Protocol, Sequence

from pete_e.infrastructure import log_utils

SYSTEM_PROMPT = (
    "Pete rewrites the draft into one natural Telegram message. Return only the rewritten message. "
    "No options, explanations, labels, preambles, or follow-up questions. Do not add, remove, or "
    "change facts, numbers, exercises, dates, targets, medical claims, readiness decisions, Wger "
    "status, or advice. Preserve important metrics, useful line breaks, and Telegram-friendly "
    "formatting."
)


class CoachVoiceClient(Protocol):
    def chat(self, messages: Sequence[Mapping[str, str]]) -> str: ...


class CoachVoiceService:
    """Rewrite finalized coach messages when enabled, falling back on any issue."""

    def __init__(
        self,
        *,
        enabled: bool,
        client: CoachVoiceClient | None = None,
        model_name: str | None = None,
    ) -> None:
        self.enabled = enabled
        self.client = client
        self.model_name = model_name

    def rewrite(self, draft_message: str) -> str:
        if not self.enabled or self.client is None or not draft_message.strip():
            return draft_message

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Rewrite this draft only:\n\n{draft_message}"},
        ]

        start = perf_counter()
        try:
            rewritten = self.client.chat(messages)
            if not isinstance(rewritten, str) or not rewritten.strip():
                raise ValueError("voice rewrite returned empty content")
            duration_ms = int((perf_counter() - start) * 1000)
            model = self.model_name or str(getattr(self.client, "model", "unknown"))
            log_utils.info(f"Pete voice rewrite succeeded model={model} duration_ms={duration_ms}")
            return rewritten
        except Exception as exc:
            log_utils.warn(f"Pete voice rewrite failed; using original message: {exc}")
            return draft_message
