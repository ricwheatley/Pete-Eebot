#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Wger Routine builder (public wger.de compatible)

- Accepts BOTH plan schemas:
  (A) Legacy weekly-cycle schema
      {
        "routine": {"name": "...", "start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "fit_in_week": true},
        "days": [
          {
            "order": 1,
            "name": "Lower",
            "type": "custom"|"hiit",
            "is_rest": false,
            "description": "...",
            "exercises": [
              {
                "name": "Barbell Squat",
                "exercise_id": null|123,
                "sets": 4,
                "reps": "5"|"6-8",
                "rir": 2,
                "rest_s": 180,
                "weight_kg": null|60.0,
                "superset_id": null|"A"
              }
            ]
          }
        ]
      }

  (B) Dated day/slot schema
      {
        "routine_name": "PeteE Block ...",
        "start_date": "YYYY-MM-DD",
        "end_date":   "YYYY-MM-DD",
        "fit_in_week": true,
        "days": [
          {
            "date": "YYYY-MM-DD",
            "name": "Lower",
            "is_rest": false,
            "class_placeholder": false,
            "slots": [
              {
                "order": 1,
                "items": [
                  {
                    "name": "Barbell Squat",
                    "equipment": "Barbell",
                    "category": "Legs",
                    "sets": 4,
                    "reps": 5|"6-8",
                    "rir": 2,
                    "rest_seconds": 180,
                    "weight": null|60.0,
                    "exercise_id": null|123
                  }
                ]
              }
            ]
          }
        ]
      }

- Works with public API endpoints shown on wger.de API root:
  /routine/, /day/, /slot/, /slot-entry/,
  /sets-config/, /repetitions-config/, /max-repetitions-config/,
  /rest-config/, /rir-config/, /weight-config/

Docs: Routine needs start & end; slot-entry + config endpoints are available on the public server.
"""

from __future__ import annotations
import argparse, os, sys, json, time, re
from typing import Any, Dict, List, Optional, Tuple
import requests

DEFAULT_BASE = "https://wger.de/api/v2"
HTTP_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_SLEEP = 1.0

# ---------------- Logging ----------------
def info(msg: str):  print(msg, flush=True)
def warn(msg: str):  print(f"[WARN] {msg}", flush=True)
def err(msg: str):   print(f"[ERROR] {msg}", flush=True)

# ---------------- HTTP helpers ----------------
def get_env() -> Tuple[str, Dict[str,str]]:
    # Fall back to default when env var is present but empty
    base = (os.environ.get("WGER_BASE_URL") or DEFAULT_BASE).rstrip("/")
    key  = os.environ.get("WGER_API_KEY", "").strip()
    if not key:
        err("WGER_API_KEY not set")
        sys.exit(1)
    headers = {
        "Authorization": f"Token {key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    return base, headers

def req(method: str, url: str, headers: Dict[str,str], payload: Optional[Dict[str,Any]]=None,
        params: Optional[Dict[str,Any]]=None, ok=(200,201), dry_run=False) -> requests.Response:
    for attempt in range(1, MAX_RETRIES+1):
        try:
            if dry_run and method.upper() in ("POST","PUT","PATCH","DELETE"):
                info(f"DRY RUN {method} {url} "
                     f"{'params='+str(params) if params else ''} "
                     f"{'payload='+json.dumps(payload) if payload else ''}")
                class Dummy:
                    status_code=200
                    def json(self): return {"dry_run": True}
                    def raise_for_status(self): return
                return Dummy()  # type: ignore
            r = requests.request(method.upper(), url, headers=headers, json=payload,
                                 params=params, timeout=HTTP_TIMEOUT)
            if r.status_code not in ok:
                body = r.text if hasattr(r, "text") else "<no body>"
                err(f"{method} {url} -> {r.status_code}: {body[:800]}")
                r.raise_for_status()
            return r
        except Exception:
            if attempt == MAX_RETRIES:
                raise
            time.sleep(RETRY_SLEEP)

def GET(base: str, headers: Dict[str,str], path: str, params: Optional[Dict[str,Any]]=None) -> Dict[str,Any]:
    return req("GET", f"{base}{path}", headers, params=params).json()

def POST(base: str, headers: Dict[str,str], path: str, payload: Dict[str,Any], ok=(201,), dry_run=False) -> Dict[str,Any]:
    return req("POST", f"{base}{path}", headers, payload=payload, ok=ok, dry_run=dry_run).json()

def PATCH(base: str, headers: Dict[str,str], path: str, payload: Dict[str,Any], ok=(200,)) -> Dict[str,Any]:
    return req("PATCH", f"{base}{path}", headers, payload=payload, ok=ok).json()

def DELETE(base: str, headers: Dict[str,str], path: str, ok=(200,202,204)) -> None:
    try:
        req("DELETE", f"{base}{path}", headers, ok=ok)
    except Exception as e:
        warn(f"DELETE {path} -> {e}")

# ---------------- Exercise resolution ----------------
_punct_re = re.compile(r"[^a-z0-9\s]")

def norm(s: str) -> str:
    if not s: return ""
    s = s.lower()
    s = s.replace("&"," and ")
    s = _punct_re.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

ALIASES = {
    # Common variants vs catalog names
    "knee raises": [
        "hanging knee raise","hanging knee raises","knee raise (hanging)","hanging leg raise (knees bent)"
    ],
    "bent over row": [
        "barbell bent-over row","barbell bent over row","bent-over row","barbell row","bentover row"
    ],
    "overhead press": [
        "barbell overhead press","military press","shoulder press","ohp","standing barbell press"
    ],
}

def fetch_exercise_index(base: str, headers: Dict[str,str], language_id: int = 2) -> List[Dict[str,Any]]:
    """Build an English exercise index from /exerciseinfo/."""
    out: List[Dict[str,Any]] = []
    params = {"limit": 100, "offset": 0}
    while True:
        page = GET(base, headers, "/exerciseinfo/", params=params)
        for row in page.get("results", []):
            en_name = None
            for tr in row.get("translations", []):
                if tr.get("language") == language_id and tr.get("name"):
                    en_name = tr["name"]; break
            if not en_name: continue
            eq = [e.get("name","") for e in (row.get("equipment") or [])]
            cat = (row.get("category") or {}).get("name","")
            out.append({
                "id": row["id"],
                "name": en_name,
                "name_n": norm(en_name),
                "equipment": [norm(x) for x in eq],
                "category": norm(cat),
            })
        next_url = page.get("next")
        if not next_url: break
        m = re.search(r"offset=(\d+)", next_url)
        params["offset"] = int(m.group(1)) if m else params["offset"] + 100
    info(f"[index] Loaded {len(out)} exercises")
    return out

def alias_candidates(target_n: str) -> List[str]:
    cands = [target_n]
    for canon, alist in ALIASES.items():
        canon_n = norm(canon)
        if target_n == canon_n or target_n in [norm(a) for a in alist]:
            cands = list({canon_n, *[norm(a) for a in alist], target_n})
    return cands

def score_match(target: str, row: Dict[str,Any], hint_equipment: Optional[str], hint_category: Optional[str]) -> float:
    t_tokens = set(target.split())
    r_tokens = set(row["name_n"].split())
    common = len(t_tokens & r_tokens)
    base = common / max(1, len(t_tokens))
    bonus = 0.0
    if hint_equipment and norm(hint_equipment) in row["equipment"]:
        bonus += 0.15
    if hint_category and norm(hint_category) == row["category"]:
        bonus += 0.10
    return base + bonus

def resolve_exercise_id(name: str, index: List[Dict[str,Any]], hint_equipment: Optional[str], hint_category: Optional[str]) -> Optional[int]:
    t = norm(name)
    cands = alias_candidates(t)
    best: Tuple[float, Optional[int], str] = (0.0, None, "")
    for cand in cands:
        for row in index:
            s = score_match(cand, row, hint_equipment, hint_category)
            if s > best[0]:
                best = (s, row["id"], row["name"])
    return best[1] if best[0] >= 0.5 else None

# ---------------- Routine helpers ----------------
def find_routine_by_name(base: str, headers: Dict[str,str], name: str) -> Optional[int]:
    res = GET(base, headers, "/routine/", params={"search": name, "limit": 50})
    items = res.get("results", []) if isinstance(res, dict) else []
    for it in items:
        if (it.get("name") or "") == name:
            return int(it["id"])
    return None

def create_or_update_routine(base: str, headers: Dict[str,str], name: str,
                             start: str, end: str,
                             fit_in_week: Optional[bool],
                             description: Optional[str],
                             dry_run: bool) -> int:
    """
    Public server requires start & end on /routine/.
    Docs: routine has name, description, start date, end date, optional fit_in_week.
    """
    name = (name or "PeteE Routine").strip()[:50]
    payload = {"name": name, "start": start, "end": end}
    if description: payload["description"] = description[:1000]
    if fit_in_week is not None: payload["fit_in_week"] = bool(fit_in_week)

    rid = find_routine_by_name(base, headers, name)
    if rid:
        info(f"[OK] Using existing routine id={rid} name={name} (will replace days)")
        # update routine window to match plan
        try:
            PATCH(base, headers, f"/routine/{rid}/", payload)
        except Exception as e:
            warn(f"PATCH /routine/{rid}/ failed (will proceed): {e}")
        # remove existing days for a clean build
        try:
            lst = GET(base, headers, "/day/", params={"routine": rid, "limit": 200})
            for d in lst.get("results", []):
                DELETE(base, headers, f"/day/{d['id']}/")
        except Exception as e:
            warn(f"Could not list/delete existing days: {e}")
        return rid

    res = POST(base, headers, "/routine/", payload, dry_run=dry_run)
    rid = int(res["id"])
    info(f"[OK] Created routine id={rid} name={name}")
    return rid

def create_day(base, headers, routine_id: int, order: int, name: str, is_rest: bool, dry_run: bool) -> int:
    payload = {"routine": routine_id, "order": int(order), "name": (name or f'Day {order}')[:50], "is_rest": bool(is_rest)}
    res = POST(base, headers, "/day/", payload, dry_run=dry_run)
    did = int(res["id"])
    info(f"  [day] {order} {name[:50]} → id={did} is_rest={is_rest}")
    return did

def create_slot(base, headers, day_id: int, order: int, dry_run: bool) -> int:
    payload = {"day": day_id, "order": int(order)}
    res = POST(base, headers, "/slot/", payload, dry_run=dry_run)
    sid = int(res["id"])
    info(f"    [slot] order={order} id={sid}")
    return sid

def create_slot_entry(base, headers, slot_id: int, exercise_id: int, dry_run: bool) -> int:
    payload = {"slot": slot_id, "exercise": exercise_id}
    res = POST(base, headers, "/slot-entry/", payload, dry_run=dry_run)
    return int(res["id"])

def post_config_row(base, headers, endpoint: str, slot_id: int, slot_entry_id: int, payload_core: Dict[str,Any], dry_run: bool):
    """
    Be compatible across deployments: try both FK field names
      1) slot_config: <slot-entry id>
      2) slot: <slot id>
    """
    for variant in ({"slot_config": slot_entry_id}, {"slot": slot_id}):
        payload = {**variant, **payload_core}
        try:
            POST(base, headers, f"/{endpoint}/", payload, dry_run=dry_run)
            return
        except Exception:
            continue
    POST(base, headers, f"/{endpoint}/", {**{"slot": slot_id}, **payload_core}, dry_run=dry_run)

# ---------------- Plan loading (supports both schemas) ----------------
def load_plan(path: str) -> Dict[str,Any]:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    out: Dict[str,Any] = {
        "name": "",
        "start": None,
        "end": None,
        "fit_in_week": None,
        "description": None,
        "days": []  # each: {order, name, is_rest, class_placeholder, slots:[{order, items:[...]}]}
    }

    if isinstance(raw, dict) and "routine" in raw:
        # Legacy weekly-cycle schema
        r = raw.get("routine") or {}
        out["name"] = (r.get("name") or "PeteE Block").strip()
        out["start"] = r.get("start")
        out["end"] = r.get("end")
        out["fit_in_week"] = r.get("fit_in_week")
        out["description"] = r.get("description")

        days = raw.get("days") or []
        for d in days:
            order = int(d.get("order") or 1)
            name  = (d.get("name") or f"Day {order}").strip()
            is_rest = bool(d.get("is_rest", False))
            is_class = (d.get("type") == "hiit") and not (d.get("exercises") or [])
            # Group exercises into slots by superset_id
            exs = d.get("exercises") or []
            buckets: Dict[str, List[Dict[str,Any]]] = {}
            idx = 0
            for ex in exs:
                key = ex.get("superset_id")
                if key is None:
                    idx += 1
                    key = f"__single_{idx}"
                buckets.setdefault(str(key), []).append(ex)

            slots = []
            s_order = 1
            for _, items in buckets.items():
                slot_items = []
                for ex in items:
                    slot_items.append({
                        "name": ex.get("name"),
                        "equipment": None,
                        "category": None,
                        "sets": ex.get("sets"),
                        "reps": ex.get("reps"),
                        "rir": ex.get("rir"),
                        "rest_seconds": ex.get("rest_s"),
                        "weight": ex.get("weight_kg"),
                        "exercise_id": ex.get("exercise_id"),
                    })
                slots.append({"order": s_order, "items": slot_items})
                s_order += 1

            out["days"].append({
                "order": order,
                "name": name,
                "is_rest": is_rest,
                "class_placeholder": bool(is_class),
                "slots": slots
            })
        return out

    elif isinstance(raw, dict) and "routine_name" in raw:
        # Dated day/slot schema
        out["name"] = (raw.get("routine_name") or "PeteE Routine").strip()
        out["start"] = raw.get("start_date")
        out["end"] = raw.get("end_date")
        out["fit_in_week"] = raw.get("fit_in_week")
        out["description"] = raw.get("description")

        for idx, d in enumerate(raw.get("days") or [], start=1):
            name  = (d.get("name") or f"Day {idx}").strip()
            is_rest = bool(d.get("is_rest", False))
            is_class = bool(d.get("class_placeholder", False))
            slots = d.get("slots") or []
            norm_slots = []
            for s in slots:
                norm_slots.append({
                    "order": int(s.get("order") or len(norm_slots)+1),
                    "items": [
                        {
                            "name": it.get("name"),
                            "equipment": it.get("equipment"),
                            "category": it.get("category"),
                            "sets": it.get("sets"),
                            "reps": it.get("reps"),
                            "rir": it.get("rir"),
                            "rest_seconds": it.get("rest_seconds"),
                            "weight": it.get("weight"),
                            "exercise_id": it.get("exercise_id"),
                        } for it in (s.get("items") or [])
                    ]
                })
            out["days"].append({
                "order": idx,
                "name": name,
                "is_rest": is_rest,
                "class_placeholder": is_class,
                "slots": norm_slots
            })
        return out

    else:
        raise ValueError("Unrecognized plan schema: expected keys 'routine' or 'routine_name'")

# ---------------- Main apply ----------------
def build_from_plan(plan_path: str, routine_name_override: Optional[str], dry_run: bool):
    base, headers = get_env()
    info(f"[wger] Base URL: {base}")
    info(f"[wger] Dry run: {'YES' if dry_run else 'NO'}")
    info(f"[wger] Reading plan: {plan_path}")

    plan = load_plan(plan_path)
    name = (routine_name_override or plan["name"] or "PeteE Routine").strip()
    start = plan.get("start")
    end   = plan.get("end")
    fit_in_week = plan.get("fit_in_week")
    description = plan.get("description")

    if not start or not end:
        err("Plan is missing 'start'/'end' dates (required by /routine/). "
            "Add routine.start/end in legacy schema or start_date/end_date in dated schema.")
        sys.exit(1)

    # Exercise index
    ex_index = fetch_exercise_index(base, headers, language_id=2)

    # Upsert routine by name; wipe days before rebuilding
    rid = create_or_update_routine(base, headers, name, start, end, fit_in_week, description, dry_run)

    # Build days
    for day in sorted(plan["days"], key=lambda x: int(x.get("order", 999))):
        did = create_day(base, headers, rid,
                         int(day.get("order", 1)),
                         day.get("name") or "Day",
                         bool(day.get("is_rest", False)),
                         dry_run)

        if day.get("is_rest") or day.get("class_placeholder") or not day.get("slots"):
            continue

        for slot in sorted(day["slots"], key=lambda s: int(s.get("order", 1))):
            sid = create_slot(base, headers, did, int(slot.get("order", 1)), dry_run)
            for item in (slot.get("items") or []):
                ex_id = item.get("exercise_id")
                if not ex_id:
                    ex_id = resolve_exercise_id(item.get("name",""), ex_index,
                                                item.get("equipment"), item.get("category"))
                if not ex_id:
                    warn(f"Could not resolve exercise_id for '{item.get('name')}'. Skipping.")
                    continue

                seid = create_slot_entry(base, headers, sid, int(ex_id), dry_run)

                # Defaults to avoid nulls
                sets = item.get("sets");  sets = int(sets) if sets is not None else 3
                reps = item.get("reps")   # int or "6-8"
                rest = item.get("rest_seconds"); rest = int(rest) if rest is not None else 90
                rir  = item.get("rir");  rir  = int(rir)  if rir  is not None else 2
                weight = item.get("weight")
                if weight is not None:
                    try: weight = float(weight)
                    except Exception: weight = None

                # Config rows
                post_config_row(base, headers, "sets-config", sid, seid, {"value": float(sets)}, dry_run)

                # reps: support range
                if isinstance(reps, str) and "-" in reps:
                    lo, hi = reps.split("-", 1)
                    post_config_row(base, headers, "repetitions-config",     sid, seid, {"value": float(lo)}, dry_run)
                    post_config_row(base, headers, "max-repetitions-config", sid, seid, {"value": float(hi)}, dry_run)
                else:
                    val = int(reps) if reps is not None else 10
                    post_config_row(base, headers, "repetitions-config", sid, seid, {"value": float(val)}, dry_run)

                post_config_row(base, headers, "rest-config", sid, seid, {"value": float(rest)}, dry_run)
                post_config_row(base, headers, "rir-config",  sid, seid, {"value": float(rir)},  dry_run)

                if weight is not None:
                    post_config_row(base, headers, "weight-config", sid, seid, {"value": float(weight)}, dry_run)

    info("[DONE] Plan applied.")

# ---------------- CLI ----------------
def main():
    ap = argparse.ArgumentParser(description="Apply a plan JSON as a Wger routine (public server compatible)")
    ap.add_argument("plan", help="Path to plan JSON")
    ap.add_argument("--routine-name", default=None, help="Override routine name")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    build_from_plan(args.plan, routine_name_override=args.routine_name, dry_run=args.dry_run)

if __name__ == "__main__":
    main()
