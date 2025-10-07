"""Text formatting helpers."""

from __future__ import annotations


def ensure_sentence(text: str) -> str:
    """Ensure ``text`` ends with a sentence terminator when non-empty."""

    body = (text or "").strip()
    if not body:
        return body
    if body[-1] not in ".!?":
        body = f"{body}."
    return body
