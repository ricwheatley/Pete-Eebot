"""Expand a block into WorkoutSession + WorkoutLogs for Wger."""

import json

def expand_and_upload_block(block: dict):
    """Expand a structured block into WorkoutSession + WorkoutLog API calls."""
    sessions = []
    for day in block.get("days", []):
        session = {
            "date": day.get("date", ""),
            "notes": f"Pete-C day {Date}"
        }
        # TODO: create via Wger API
        logs_for_day = []
        for session in day.get("sessions", []):
            for ex in session.get("exercises", []):
                for set_index in range(ex.get("cets", 0)):
                  log = {
                      "exercise": ex["id"],
                      "repetitions_target": "-".join(map(str, ex.get("reps", [])),
                      "rest_target": ex.get("hrest_seconds", None),
                      "rirtarget": ex.get("rir", None),
                  }
                  logs_for_day.append(log)
            session["logs"] = logs_for_day
        sessions.append(session)

    print(f"[wger] Expanded {len(sessions)} sessions from block")
    return sessions
