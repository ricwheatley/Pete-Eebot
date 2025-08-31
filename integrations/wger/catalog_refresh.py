#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Pull the full exercise catalog from wger and write:
- integrations/wger/catalog/exercises_en.json
- integrations/wger/catalog/exercises_en.csv

Uses the public `exerciseinfo` endpoint (no auth), paginates via `next`.
English translation is preferred (language==2); falls back to first available.
"""

import csv
import json
import os
import sys
from typing import Any, Dict, List, Optional
import requests

BASE = (os.environ.get("WGER_BASE_URL") or "https://wger.de/api/v2").strip().rstrip("/")

OUT_DIR = "integrations/wger/catalog"
JSON_OUT = os.path.join(OUT_DIR, "exercises_en.json")
CSV_OUT  = os.path.join(OUT_DIR, "exercises_en.csv")

def fetch_all(url: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    next_url = url
    while next_url:
        r = requests.get(next_url, params=params if next_url == url else None, timeout=30)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and "results" in data:
            results.extend(data["results"])
            next_url = data.get("next")
        elif isinstance(data, list):
            results.extend(data)
            next_url = None
        else:
            break
    return results

def pick_english_name_desc(translations: List[Dict[str, Any]]) -> Dict[str, str]:
    name = ""
    desc = ""
    if not isinstance(translations, list):
        return {"name": "", "description": ""}
    # Prefer English (language==2), else first available
    en = next((t for t in translations if t.get("language") == 2 and t.get("name")), None)
    chosen = en or next((t for t in translations if t.get("name")), None)
    if chosen:
        name = chosen.get("name") or ""
        desc = (chosen.get("description") or "").strip()
    return {"name": name, "description": desc}

def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"[wger] Fetching catalog from: {BASE}/exerciseinfo/")
    rows = fetch_all(f"{BASE}/exerciseinfo/", params={"limit": 200})  # server will include `next` link

    tidy: List[Dict[str, Any]] = []
    for ex in rows:
        ex_id = ex.get("id")
        uuid = ex.get("uuid")
        cat  = (ex.get("category") or {}).get("name", "")
        equip_list = [e.get("name","") for e in (ex.get("equipment") or [])]
        mus_p = [m.get("name_en") or m.get("name","") for m in (ex.get("muscles") or [])]
        mus_s = [m.get("name_en") or m.get("name","") for m in (ex.get("muscles_secondary") or [])]
        lic   = (ex.get("license") or {}).get("short_name","") or (ex.get("license") or {}).get("full_name","")
        eng   = pick_english_name_desc(ex.get("translations") or [])

        tidy.append({
            "id": ex_id,
            "uuid": uuid,
            "name": eng["name"],
            "category": cat,
            "equipment": equip_list,
            "muscles_primary": mus_p,
            "muscles_secondary": mus_s,
            "license": lic,
            "description_html": eng["description"],   # raw HTML from API
        })

    # JSON
    with open(JSON_OUT, "w", encoding="utf-8") as jf:
        json.dump(tidy, jf, ensure_ascii=False, indent=2)

    # CSV
    fieldnames = [
        "id","uuid","name","category",
        "equipment","muscles_primary","muscles_secondary","license","description_html"
    ]
    with open(CSV_OUT, "w", encoding="utf-8", newline="") as cf:
        w = csv.DictWriter(cf, fieldnames=fieldnames)
        w.writeheader()
        for t in tidy:
            w.writerow({
                **t,
                "equipment": "; ".join(t["equipment"]),
                "muscles_primary": "; ".join(t["muscles_primary"]),
                "muscles_secondary": "; ".join(t["muscles_secondary"]),
            })

    print(f"[wger] Wrote {len(tidy)} rows → {JSON_OUT} and {CSV_OUT}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
