"""Expansion of training block into Wger sessions + logs."""

def expand_and_upload_block(block: dict):
    """Expand a structured block into WorkoutSession + WorkoutLog API calls."""
    # TODO: implement mapping:
    #  - Each day -> WorkoutSession
    #  - Each exercise -> WorkoutLog entries (expanded per set)
    #  - Respect rest, superset, progression targets
    print(f[wger] expand_and_upload_block called with {len(block.get('days', []))} days)")
    return []