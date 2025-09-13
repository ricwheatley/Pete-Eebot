import json
import random

# Import centralized components
from pete_e.config import settings
from pete_e.infra.log_utils import log_message

# Global cache for phrases to avoid repeated file reads
_all_phrases = None


def load_phrases():
    """Load phrases from JSON into memory (cached)."""
    global _all_phrases
    if _all_phrases is None:
        phrases_path = settings.PHRASES_PATH
        if not phrases_path.exists():
            log_message(f"Missing phrases file at {phrases_path}", "ERROR")
            # Return an empty list to prevent crashes, but log the error
            return []
        _all_phrases = json.loads(phrases_path.read_text(encoding="utf-8"))
    return _all_phrases


def random_phrase(kind="any", mode="balanced", tags=None) -> str:
    """
    Pick a random phrase from Pete’s arsenal.

    kind: motivational, silly, portmanteau, metaphor, coachism, legendary, or any
    mode: serious | chaotic | balanced
    tags: optional list of hashtags to filter (e.g. ["#Motivation"])
    """
    phrases = load_phrases()
    if not phrases:
        return "No phrases available. Check logs for errors."

    # 1% chance to drop a legendary easter egg
    legendary = [p for p in phrases if (p.get("mode") or "").lower() == "legendary"]
    if legendary and random.random() < 0.01:
        return random.choice(legendary)["text"]

    # Filter by tags
    if tags:
        tagset = set(tags)
        phrases = [p for p in phrases if tagset & set(p.get("tags", []))]

    # Filter by kind (only if tags not used)
    elif kind != "any":
        phrases = [p for p in phrases if kind == (p.get("kind") or "").lower()]

    # Mode selection
    serious = [p for p in phrases if (p.get("mode") or "").lower() in ("motivational", "coachism")]
    chaotic = [p for p in phrases if (p.get("mode") or "").lower() in ("silly", "portmanteau", "metaphor")]

    if mode == "serious":
        phrases = serious
    elif mode == "chaotic":
        phrases = chaotic
    elif mode == "balanced":
        # Default to serious 80% of the time, otherwise chaotic
        if random.random() < 0.8 and serious:
            phrases = serious
        elif chaotic:
            phrases = chaotic
    else:
        log_message(f"Unknown mode specified: {mode}", "WARN")

    if not phrases:
        # Fallback to a generic phrase if no specific matches are found
        return "Let's get to work."

    return random.choice(phrases)["text"]
