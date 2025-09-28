from fastapi import FastAPI, Query, HTTPException, Header
import psycopg
from pete_e.config import settings  # loads .env via BaseSettings

app = FastAPI(title="Pete-Eebot API")

@app.get("/metrics_overview")
def metrics_overview(
    date: str = Query(..., description="Date in YYYY-MM-DD"),
    x_api_key: str = Header(None)
):
    """
    Run sp_metrics_overview(date) and return columns + rows as JSON.
    Requires X-API-Key header.
    """
    # API key check
    if x_api_key != settings.PETEEEBOT_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    if not settings.DATABASE_URL:
        raise HTTPException(status_code=500, detail="DATABASE_URL not configured")

    try:
        with psycopg.connect(settings.DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM sp_metrics_overview(%s)", (date,))
                rows = cur.fetchall()
                cols = [desc[0] for desc in cur.description]

        return {"columns": cols, "rows": rows}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
