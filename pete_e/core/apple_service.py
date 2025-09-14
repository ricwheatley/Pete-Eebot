from fastapi import FastAPI, Request, HTTPException
from datetime import date
from pete_e.core import apple_client
from pete_e.core.sync import _get_dal
from pete_e.infra import log_utils

app = FastAPI()
dal = _get_dal()

@app.post("/apple")
async def ingest_apple(req: Request):
    try:
        payload = await req.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    # Normalise with existing client logic
    summary = apple_client.get_apple_summary(payload)

    # Save to DAL
    day = summary.get("date") or date.today().isoformat()
    dal.save_daily_summary({"apple": summary, "withings": {}, "wger": {}}, date.fromisoformat(day))

    log_utils.log_message(f"Apple data ingested for {day}", "INFO")
    return {"status": "ok", "saved_date": day}
