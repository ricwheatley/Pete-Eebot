import json, os, sys, time
import requests
from datetime import datetime

BASE_URL = os.environ.get("WGER_BASE_URL", "https://wger.de/api/v2")
API_KEY = os.environ.get("WGER_API_KEY")

if not API_KEY:
    print("ERROR: WGER_API_KEY is not set.")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Token {API_KEY}",
    "Content-Type": "application/json"
}

def post_json(endpoint, payload, max_retries=3, backoff=2.0):
    url = f"{BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    for attempt in range(1, max_retries+1):
        r = requests.post(url, headers=HEADERS, json=payload, timeout=30)
        if 200 <= r.status_code < 300:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
            time.sleep(backoff * attempt)
            continue
        print(f"Request failed ({r.status_code}): {r.text}")
        r.raise_for_status()

def create_placeholder_workout(date_str, title, comment):
    # NOTE: This uses the generic 'workout' creation endpoint. Depending on your wger setup,
    # you may prefer creating 'workout' + 'day' + 'set' models, or a 'workoutsession' if available.
    # This placeholder approach ensures something appears on the correct date with clear notes.
    payload = {
        "comment": f"{title} â {date_str} â {comment}"
    }
    # wger Workout endpoint
    return post_json("/workout/", payload)

def main():
    if len(sys.argv) < 2:
        print("Usage: python wger_upload.py <schedule.json> [--dry-run]")
        sys.exit(2)

    schedule_path = sys.argv[1]
    dry_run = "--dry-run" in sys.argv

    with open(schedule_path, "r") as f:
        data = json.load(f)

    entries = data.get("entries", [])
    created = []
    for e in entries:
        if e["kind"] not in ("weights", "class"):
            continue  # only upload weights and Blaze placeholders
        date_str = e["date"]
        title = e["title"]
        time_str = (" @ " + e["time"]) if e.get("time") else ""
        duration = e.get("duration_min")
        rpe = e.get("rpe_target")
        details = e.get("details", {})
        note_bits = []
        if duration: note_bits.append(f"{duration} min")
        if rpe: note_bits.append(f"RPE {rpe}")
        if details.get("notes"): note_bits.append(details["notes"])
        if details.get("exercises"):
            ex_lines = []
            for x in details["exercises"]:
                ex_lines.append(f"- {x['name']}: {x['sets']} x {x['reps']} @ RPE {x.get('RPE','â')}")
            note_bits.append("Exercises:\n" + "\n".join(ex_lines))

        comment = f"{title}{time_str}"
        if note_bits:
            comment += " | " + " | ".join(note_bits)

        if dry_run:
            print(f"[DRY RUN] Would create workout: {date_str} â {comment}")
        else:
            res = create_placeholder_workout(date_str, title, comment)
            created.append({"date": date_str, "title": title, "id": res.get("id")})

    print(json.dumps({"created": created}, indent=2))

if __name__ == "__main__":
    main()