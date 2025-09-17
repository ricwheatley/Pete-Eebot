# pete_e/core/wger_exporter_v2.py

import os
import requests
from typing import Any, Dict, List, Optional

from pete_e.data_access.plan_rw import plan_week_rows, log_wger_export
from pete_e.core.schedule_rules import SQUAT_ID, BENCH_ID, DEADLIFT_ID, OHP_ID

WGER_API_BASE = os.getenv("WGER_API_BASE", "https://wger.de/api/v2")
WGER_API_KEY = os.getenv("WGER_API_KEY")  # personal token

MAIN_LIFTS = {SQUAT_ID, BENCH_ID, DEADLIFT_ID, OHP_ID}
TEST_PCTS = {85.0, 87.5, 90.0}

def _is_amrap_test_row(row: Dict[str, Any]) -> bool:
    return (
        row.get("exercise_id") in MAIN_LIFTS
        and row.get("sets") == 1
        and row.get("reps") == 1
        and (row.get("percent_1rm") in TEST_PCTS)
    )

def _comment(row: Dict[str, Any]) -> str:
    parts = []
    if row.get("percent_1rm") is not None:
        parts.append(f"{row['percent_1rm']:.1f}% 1RM")
    if row.get("rir") is not None:
        parts.append(f"RIR {row['rir']:.1f}")
    if row.get("target_weight_kg") is not None:
        parts.append(f"{row['target_weight_kg']:.1f} kg")
    if _is_amrap_test_row(row):
        parts.append("AMRAP test")
    return ", ".join(parts)

def _payload_for_week(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_day: Dict[int, List[Dict[str, Any]]] = {}
    for r in rows:
        if r["is_cardio"]:
            entry = {"exercise": r["exercise_id"], "sets": r["sets"], "reps": r["reps"], "comment": "Blaze HIIT"}
        else:
            entry = {"exercise": r["exercise_id"], "sets": r["sets"], "reps": r["reps"], "comment": _comment(r)}
        by_day.setdefault(r["day_of_week"], []).append(entry)

    days_payload = []
    for dow in sorted(by_day.keys()):
        days_payload.append({"day_of_week": dow, "exercises": by_day[dow]})
    return {"days": days_payload}

def export_week(plan_id: int, week_number: int) -> Dict[str, Any]:
    rows = plan_week_rows(plan_id, week_number)
    payload = _payload_for_week(rows)

    response_json: Optional[Dict[str, Any]] = None
    if WGER_API_KEY:
        url = f"{WGER_API_BASE}/workout/"
        headers = {"Authorization": f"Token {WGER_API_KEY}"}
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        try:
            response_json = response.json()
        except Exception:
            response_json = {"status_code": response.status_code, "text": response.text}

    log_wger_export(plan_id, week_number, payload, response_json)
    return {"payload": payload, "response": response_json}
