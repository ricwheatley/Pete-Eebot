import json
import pathlib
import random

PHRASES_PATH = pathlib.Path("integrations/pete_feedback/phrases_tagged.json")


def load_phrases():
    if not PHRASES_PATH.exists():
        raise FileNotFoundError(f"Phrases file not found: {PHRASES_PATH}")
    return json.loads(PHRASES_PATH.read_text())


def phrase_for(required_tags=None):
    """
    Select a random phrase that matches the given list of tags.
    If no match, fall back to #Motivation.
    """
    phrases = load_phrases()
    if not required_tags:
        return random.choice(phrases)["text"]

    required_tags = set(required_tags)
    matches = [p for p in phrases if required_tags.issubset(set(p.get("tags", [])))]

    if matches:
        return random.choice(matches)["text"]

    # fallback to motivational
    motivation_matches = [p for p in phrases if "#Motivation" in p.get("tags", [])]
    if motivation_matches:
        return random.choice(motivation_matches)["text"]

    # final fallback — return anything
    return random.choice(phrases)["text"]


if __name__ == "__main__":
    # Example usage
    print(phrase_for(["#Bench", "#PR"]))
    print(phrase_for(["#Recovery"]))
    print(phrase_for(["#Cardio"]))
    print(phrase_for())
