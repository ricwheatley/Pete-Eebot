"""General helper utilities shared across Pete-E."""

from __future__ import annotations

import random
from typing import List


def choose_from(options: List[str], default: str = "", rand=None) -> str:
    """Return a random element from ``options`` or ``default`` when empty."""

    rng = rand or random
    if not options:
        return default
    try:
        return rng.choice(options)
    except IndexError:
        return default or options[0]
