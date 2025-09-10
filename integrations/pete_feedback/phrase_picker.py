import json, random, pathlib

PHRASES_PATH = pathlib.Path("integrations/pete_feedback/phrases_tagged.json")
_all_phrases = None

def load_phrases():
    global _all_phrases
    if _all_phrases is None:
        _all_phrases = json.loads(PHRASES_PATH.read_text(encoding="utf-8"))
    return _all_phrases

def random_phrase(mode=None, tags=None):
    phrases = load_phrases()

    # Mode filter
    if mode:
        phrases = [p for p in phrases if p["mode"] == mode]

    # Tag filter
    if tags:
        tagset = set(tags)
        phrases = [p for p in phrases if tagset & set(p["tags"])]

    if not phrases:
        raise ValueError(f"No phrases found for mode={mode}, tags={tags}")

    return random.choice(phrases)["text"]
