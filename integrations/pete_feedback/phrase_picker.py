import json, random, pathlib

PHRASES_PATH = pathlib.Path("integrations/pete_feedback/phrases_tagged.json")
_all_phrases = None


def load_phrases():
    """Load phrases from JSON into memory (cached)."""
    global _all_phrases
    if _all_phrases is None:
        _all_phrases = json.loads(PHRASES_PATH.read_text(encoding="utf-8"))
    return _all_phrases


def random_phrase(kind="any", mode="balanced", tags=None) -> str:
    """
    Pick a random phrase from Pete's arsenal.

    kind: motivational, silly, portmanteau, metaphor, coachism, legendary, or any
    mode: serious | chaotic | balanced
    tags: optional list of hashtags to filter (e.g. ["#Motivation"])
    """
    phrases = load_phrases()

    # 1% chance to drop a legendary easter egg
    legendary = [p for p in phrases if (p.get("mode") or "").lower() == "legendary"]
    if legendary and random.random() < 0.01:
        return random.choice(legendary)["text"]

    # Filter by tags
    if tags:
        tagset = set(tags)
        phrases = [p for p in phrases if tagset & set(p.get("tags", []))]

    # Filter by kind (only if tags not used)
    if kind != "any" and not tags:
        phrases = [p for p in phrases if kind == (p.get("mode") or "").lower()]

    # Map higher-level Pete modes to categories
    if mode == "serious":
        phrases = [p for p in phrases if (p.get("mode") or "").lower() in ("motivational", "coachism")]
    elif mode == "chaotic":
        phrases = [p for p in phrases if (p.get("mode") or "").lower() in ("silly", "portmanteau", "metaphor")]
    elif mode == "balanced":
        pass  # keep everything
    else:
        raise ValueError(f"Unknown mode: {mode}")

    if not phrases:
        raise ValueError(f"No phrases found for kind={kind}, mode={mode}, tags={tags}")

    return random.choice(phrases)["text"]