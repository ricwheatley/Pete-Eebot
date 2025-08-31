#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fetch and cache the Wger exercise catalog + equipment, muscles, categories.

Writes:
- integrations/wger/catalog/exercises_en.json
- integrations/wger/catalog/exercises_en.csv
- integrations/wger/catalog/equipment.json
- integrations/wger/catalog/muscles.json
- integrations/wger/catalog/exercisecategory.json
"""
import csv
import json
import os
import sys
from typing import Any, Dict, List, Optional
import requests

BASE = (os.environ.get("WGER_BASE_URL") or "https://wger.de/api/v2").strip().rstrip("/")

OUT_DIR = "integrations/wger/catalog"
EX_JSON = os.path.join(OUT_DIR, "exercises_en.json")
EX_CSV  = os.path.join(OUT_DIR, "exercises_en.csv")

def fetch_all(url: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    next_url = url
    while next_url:
        r = requests.get(next_url, params=params if next_url == url else None, timeout=60)
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

def pick_english(translations: List[Dict[str, Any]]) -> Dict[str, str]:
    """Prefer English (language==2); fallback to any with name."""
    name = ""
    desc = ""
    if not isinstance(translations, list):
        return {"name": "", "description": ""}
    en = next((t for t in translations if t.get("language") == 2 and t.get("name")), None)
    chosen = en or next((t for t in translations if t.get("name")), None)
    if chosen:
        name = chosen.get("name") or ""
        desc = (chosen.get("description") or "").strip()
    return {"name": name, "description": desc}

def refresh_exercises() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"[wger] Fetching exercises from: {BASE}/exerciseinfo/")
    rows = fetch_all(f"{BASE}/exerciseinfo/", params={"limit": 200})

    tidy: List[Dict[str, Any]] = []
    for ex in rows:
        ex_id = ex.get("id")
        uuid = ex.get("uuid")
        cat  = (ex.get("category") or {}).get("name", "")
        equip_list = [e.get("name","") for e in (ex.get("equipment") or [])]
        mus_p = [m.get("name_en") or m.get("name","") for m in (ex.get("muscles") or [])]
        mus_s = [m.get("name_en") or m.get("name","") for m in (ex.get("muscles_secondary") or [])]
        lic   = (ex.get("license") or {}).get("short_name","") or (ex.get("license") or {}).get("full_name","")
        eng   = pick_english(ex.get("translations") or [])

        tidy.append({
            "id": ex_id,
            "uuid": uuid,
            "name": eng["name"],
            "category": cat,
            "equipment": equip_list,
            "muscles_primary": mus_p,
            "muscles_secondary": mus_s,
            "license": lic,
            "description_html": eng["description"],
        })

    with open(EX_JSON, "w", encoding="utf-8") as jf:
        json.dump(tidy, jf, ensure_ascii=False, indent=2)

    fieldnames = [
        "id","uuid","name","category",
        "equipment","muscles_primary","muscles_secondary","license","description_html"
    ]
    with open(EX_CSV, "w", encoding="utf-8", newline="") as cf:
        w = csv.DictWriter(cf, fieldnames=fieldnames)
        w.writeheader()
        for t in tidy:
            w.writerow({
                **t,
                "equipment": "; ".join(t["equipment"]),
                "muscles_primary": "; ".join(t["muscles_primary"]),
                "muscles_secondary": "; ".join(t["muscles_secondary"]),
            })
    print(f"[wger] Wrote {len(tidy)} rows → {EX_JSON} and {EX_CSV}")
    return len(tidy)

def refresh_simple(endpoint: str, out_file: str) -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    rows = fetch_all(f"{BASE}/{endpoint}/", params={"limit": 200})
    with open(os.path.join(OUT_DIR, out_file), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print(f"[wger] Wrote {len(rows)} rows → {out_file}")
    return len(rows)

def main() -> None:
    total = refresh_exercises()
    total += refresh_simple("equipment", "equipment.json")
    total += refresh_simple("muscle", "muscles.json")
    total += refresh_simple("exercisecategory", "exercisecategory.json")
    print(f"[wger] Catalog refresh done. Total objects: {total}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
