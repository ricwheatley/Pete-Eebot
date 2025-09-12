#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Upload day-by-day sessions to Wger via the REST API.

Supports two schedule schemas:

A) Legacy block format (object with 'entries'):
{
  "plan_name": "...",
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "timezone": "Europe/London",
  "notes": "...",
  "entries": [
    {
      "date": "YYYY-MM-DD",
      "kind": "weights" | "class" | "mobility" | "recovery",
      "title": "Weights – Lower Body" | "Blaze HIIT",
      "time": "06:15",
      "duration_min": 60,
      "rpe_target": "7–8",
      "details": {
        "notes": "optional",
        "exercises": [{"name": "...", "sets": 3, "reps": "5", "RPE": "7"}]
      }
    }, ...
  ]
}

B) Flat list-of-entries format:
[
  {
    "date": "YYYY-MM-DD",
    "type": "weights" | "class" | "rest",
    "title": "Blaze HIIT @ 06:15",
    "duration": 45,       # minutes (int)
    "feeling": 3,         # 1..5
    "notes": "optional"
  },
  ...
]

Behaviour:
- Posts to /workoutsession/ (one session per eligible day).
- Always sends numeric 'duration' and 'feeling' to avoid app crashes on null casting.
- Skips 'mobility', 'recovery', and 'rest' entries by default.
- 'upload' mode (default) creates sessions; '--dry-run' prints actions.
- 'repair' mode ('--repair') PATCHes existing sessions on dates in your JSON to ensure numeric fields are not null.

Env:
  WGER_API_KEY   (required)  -> token
  WGER_BASE_URL  (optional)  -> defaults to https://wger.de/api/v2 (no trailing slash)
"""

import json
import os
import sys
from typing import Any, Dict, List, Optional

import requests


# ---------- Config ----------

def base_url() -> str:
    base = (os.environ.get("WGER_BASE_URL") or "https://wger.de/api/v2").strip().strip("/")
    if not base.startswith("http"):
        print(f"[ERROR] WGER_BASE_URL invalid: '{base}'", file=sys.stderr)
        sys.exit(2)
    return base

def api_headers() -> Dict[str, str]:
    api_key = os.environ.get("WGER_API_KEY", "").strip()
    if not api_key:
        print("[ERROR] WGER_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)
    return {
        "Authorization": f"Token {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


# ---------- HTTP helpers ----------

def _request(method: str, path: str, *, params: Optional[Dict[str, Any]] = None,
             payload: Optional[Dict[str, Any]] = None, timeout: int = 30) -> requests.Response:
    url = f"{base_url()}{path}"
    r = requests.request(method=method.upper(), url=url, headers=api_headers(),
                         params=params, json=payload, timeout=timeout)
    if not r.ok:
        snippet = (r.text or "")[:400].replace("\n", " ")
        print(f"{method} {url} -> {r.status_code}: {snippet}", file=sys.stderr)
    r.raise_for_status()
    return r

def get_json(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    return _request("GET", path, params=params).json()

def post_json(path: str, payload: Dict[str, Any]) -> Any:
    return _request("POST", path, payload=payload).json()

def patch_json(path: str, payload: Dict[str, Any]) -> Any:
    return _request("PATCH", path, payload=payload).json()


# ---------- Normalization ----------

def _build_notes(title: str, entry: Dict[str, Any], extra: Optional[str] = None) -> str:
    parts: List[str] = []
    t = entry.get("time")
    if t:
        parts.append(f"Time: {t}")
    dur_legacy = entry.get("duration_min")
    if dur_legacy:
        parts.append(f"Planned duration: {dur_legacy} min")
    rpe = entry.get("rpe_target")
    if rpe:
        parts.append(f"RPE: {rpe}")
    details = entry.get("details") or {}
    if isinstance(details, dict):
        dnote = details.get("notes")
        if dnote:
            parts.append(dnote)
        exs = details.get("exercises")
        if isinstance(exs, list) and exs:
            lines = []
            for x in exs:
                name = x.get("name", "Exercise")
                sets = x.get("sets", "?")
                reps = x.get("reps", "?")
                rxpe = x.get("RPE", "–")
                lines.append(f"- {name}: {sets} x {reps} @ RPE {rxpe}")
            parts.append("Exercises:\n" + "\n".join(lines))
    if extra:
        parts.append(extra)
    base = f"{title} – planned via automation"
    return base + ("\n\n" + "\n".join(parts) if parts else "")

def normalize_legacy(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    kind = (entry.get("kind") or "").lower().strip()
    if kind in ("mobility", "recovery"):
        return None
    if kind not in ("weights", "class"):
        return None

    date = entry.get("date")
    if not date:
        return None

    title = entry.get("title") or ("Blaze HIIT" if kind == "class" else "Weights")
    duration_min = entry.get("duration_min")
    try:
        duration = int(duration_min) if duration_min is not None else (45 if kind == "class" else 60)
    except Exception:
        duration = 45 if kind == "class" else 60

    feeling = 3
    notes = _build_notes(title, entry)
    return {
        "date": date,
        "duration": duration,
        "feeling": feeling,
        "notes": notes,
    }

def normalize_flat(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    etype = (entry.get("type") or "").lower().strip()
    if etype in ("rest", "recovery", "mobility"):
        return None

    date = entry.get("date")
    if not date:
        return None

    title = entry.get("title") or "Session"
    duration = entry.get("duration")
    try:
        duration = int(duration) if duration is not None else 45
    except Exception:
        duration = 45

    feeling = entry.get("feeling")
    try:
        feeling = int(feeling) if feeling is not None else 3
    except Exception:
        feeling = 3
    feeling = max(1, min(5, feeling))

    extra = entry.get("notes")
    notes = f"{title} – planned via automation" + (f"\n\n{extra}" if extra else "")

    return {
        "date": date,
        "duration": duration,
        "feeling": feeling,
        "notes": notes,
    }

def load_and_normalize(schedule) -> List[Dict[str, Any]]:
    """
    Load JSON (from path or dict/list) and normalize into a list of /workoutsession/ payloads.
    Accepts both schemas (legacy object-with-entries OR flat list).
    """
    if isinstance(schedule, (dict, list)):
        data = schedule
    else:
        with open(schedule, "r", encoding="utf-8") as f:
            data = json.load(f)

    normalized: List[Dict[str, Any]] = []

    if isinstance(data, dict) and isinstance(data.get("entries"), list):
        print("[wger] Detected legacy block schema with 'entries'")
        for e in data["entries"]:
            if not isinstance(e, dict):
                continue
            n = normalize_legacy(e)
            if n:
                normalized.append(n)
    elif isinstance(data, list):
        print("[wger] Detected flat list schema")
        for e in data:
            if not isinstance(e, dict):
                continue
            n = normalize_flat(e)
            if n:
                normalized.append(n)
    else:
        raise ValueError("Unsupported schedule JSON format. Provide an object with 'entries' or a list of entries.")

    return normalized


# ---------- Upload & Repair ----------

def create_session(payload: Dict[str, Any], *, dry_run: bool = False) -> Optional[Dict[str, Any]]:
    if dry_run:
        print(f"[DRY-RUN] Would POST /workoutsession/: {json.dumps(payload, ensure_ascii=False)}")
        return None
    res = post_json("/workoutsession/", payload)
    sid = res.get("id")
    print(f"[OK] Created session {sid} on {payload.get('date')} (duration {payload.get('duration')} min, feeling {payload.get('feeling')})")
    return res

def ensure_numeric_defaults(session: Dict[str, Any]) -> Dict[str, Any]:
    patch: Dict[str, Any] = {}
    if session.get("duration") is None:
        patch["duration"] = 1
    if session.get("feeling") is None:
        patch["feeling"] = 3
    if "distance" in session and session.get("distance") is None:
        patch["distance"] = 0
    if "energy" in session and session.get("energy") is None:
        patch["energy"] = 0
    return patch

def repair_dates(dates: List[str]) -> None:
    fixed = 0
    checked = 0
    for d in sorted(set([x for x in dates if x])):
        resp = get_json("/workoutsession/", params={"date": d})
        results = resp.get("results") if isinstance(resp, dict) else resp
        if not isinstance(results, list):
            results = []
        for s in results:
            checked += 1
            sid = s.get("id")
            patch = ensure_numeric_defaults(s)
            if patch and sid:
                patch_json(f"/workoutsession/{sid}/", patch)
                fixed += 1
                print(f"[REPAIR] Patched session {sid} on {d}: {patch}")
    print(f"[REPAIR] Checked {checked} sessions, fixed {fixed} with null numeric fields.")


# ---------- Main ----------

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python integrations/wger/wger_uploads.py <schedule.json> [--dry-run|--repair]", file=sys.stderr)
        sys.exit(2)

    schedule_arg = sys.argv[1]
    dry_run = "--dry-run" in sys.argv
    do_repair = "--repair" in sys.argv

    print(f"[wger] Base URL: {base_url()}")
    print(f"[wger] Mode: {'REPAIR' if do_repair else ('DRY-RUN' if dry_run else 'UPLOAD')}")
    print(f"[wger] Reading schedule: {schedule_arg}")

    normalized_payloads = load_and_normalize(schedule_arg)
    print(f"[wger] Eligible for upload (non-rest/mobility/recovery): {len(normalized_payloads)}")

    if do_repair:
        dates = [p.get("date") for p in normalized_payloads]
        repair_dates(dates)
        return

    created = 0
    for p in normalized_payloads:
        if create_session(p, dry_run=dry_run) is not None or dry_run:
            created += 1
    print(f"[wger] Done. {'Would create' if dry_run else 'Created'} {created} session(s).")


if __name__ == "__main__":
    main()