import os, json, pathlib
from datetime import date


def load_json_env(name):
    raw = os.environ.get(name, "")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


# ---- Ingest payload (prefer nested)
data = load_json_env("CLIENT_PAYLOAD_DATA")
if not data:
    raw = load_json_env("CLIENT_PAYLOAD_RAW")
    if isinstance(raw, dict) and "data" in raw and isinstance(raw["data"], dict):
        data = raw["data"]
    else:
        data = raw

if not isinstance(data, dict) or not data:
    print("No payload received")
    raise SystemExit(0)


# ---- Helpers
def clean_num(v, as_int=True):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v) if as_int else float(v)
    s = str(v).replace(",", "").strip()
    try:
        return int(float(s)) if as_int else float(s)
    except Exception:
        return None


def clean_sleep(obj):
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, str):
        try:
            maybe = json.loads(obj)
            if isinstance(maybe, dict):
                return maybe
        except Exception:
            pass
    return {}


# ---- Normalise inputs
date_str = str(data.get("date") or date.today())
tz = data.get("timezone", "Europe/London")
src = data.get("source", "apple_shortcut")

steps = clean_num(data.get("steps"))
ex_minutes = clean_num(data.get("exercise_minutes"))
cals_active = clean_num(data.get("calories_active"))
cals_resting = clean_num(data.get("calories_resting"))
cals_total = clean_num(data.get("calories_total"))
stand_minutes = clean_num(data.get("stand_minutes"))
distance_m = clean_num(data.get("distance_m"))

hr_min = clean_num(data.get("hr_min"))
hr_max = clean_num(data.get("hr_max"))
hr_avg = clean_num(data.get("hr_avg"))
hr_resting = clean_num(data.get("hr_resting"))

sleep_dict = clean_sleep(data.get("sleep_minutes"))
sleep_asleep = clean_num(sleep_dict.get("asleep"))
sleep_awake = clean_num(sleep_dict.get("awake"))
sleep_core = clean_num(sleep_dict.get("core"))
sleep_deep = clean_num(sleep_dict.get("deep"))
sleep_in_bed = clean_num(sleep_dict.get("in_bed"))
sleep_rem = clean_num(sleep_dict.get("rem"))

# ---- JSON artefacts under docs/apple
days_dir = pathlib.Path("docs/apple/days")
days_dir.mkdir(parents=True, exist_ok=True)
daily_path = pathlib.Path("docs/apple/daily.json")
hist_p = pathlib.Path("docs/apple/history.json")

out_json = {
    "source": src,
    "date": date_str,
    "timezone": tz,
    "steps": steps,
    "hr_min": hr_min,
    "hr_max": hr_max,
    "hr_avg": hr_avg,
    "hr_resting": hr_resting,
    "exercise_minutes": ex_minutes,
    "calories_active": cals_active,
    "calories_resting": cals_resting,
    "calories_total": cals_total,
    "stand_minutes": stand_minutes,
    "distance_m": distance_m,
    "sleep_minutes": {
        "asleep": sleep_asleep,
        "awake": sleep_awake,
        "core": sleep_core,
        "deep": sleep_deep,
        "in_bed": sleep_in_bed,
        "rem": sleep_rem,
    },
}

# Write daily JSON (per-day file and "latest" daily.json)
(days_dir / f"{date_str}.json").write_text(
    json.dumps(out_json, indent=2), encoding="utf-8"
)
daily_path.write_text(json.dumps(out_json, indent=2), encoding="utf-8")

# Maintain rolling 90-day history
history = []
if hist_p.exists():
    try:
        history = json.loads(hist_p.read_text(encoding="utf-8"))
    except Exception:
        history = []

history = [h for h in history if h.get("date") != date_str]
history.append(out_json)
history = sorted(history, key=lambda x: x.get("date", ""), reverse=True)[:90]

hist_p.write_text(json.dumps(history, indent=2), encoding="utf-8")

print(
    json.dumps(
        {
            "date": date_str,
            "docs": "docs/apple",
            "files": {
                "daily": str(daily_path),
                "history": str(hist_p),
                "day_file": str(days_dir / f"{date_str}.json"),
            },
        }
    )
)