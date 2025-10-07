"""General helper utilities shared across Pete-E."""

from __future__ import annotations

import random
from typing import List


def choose_from(options: List[str], default: str = "") -> str:
    """Return a random element from ``options`` or ``default`` when empty."""

    if not options:
        return default
    try:
        return random.choice(options)
    except IndexError:
        return default or options[0]
