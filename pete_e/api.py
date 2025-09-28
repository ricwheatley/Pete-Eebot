from fastapi import FastAPI, Query, HTTPException, Header
import psycopg
import os

app = FastAPI()
DATABASE_URL = os.getenv("DATABASE_URL")
API_KEY = os.getenv("PETEEEBOT_API_KEY")  # the key you set in your env

@app.get("/metrics_overview")
def metrics_overview(
    date: str = Query(..., description="Date in YYYY-MM-DD"),
    x_api_key: str = Header(None)
):
    # Check API key
    if not API_KEY:
        raise HTTPException(status_code=500, detail="Server missing PETEEEBOT_API_KEY")
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    # Normal DB logic
    if not DATABASE_URL:
        raise HTTPException(status_code=500, detail="DATABASE_URL not set")

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM sp_metrics_overview(%s)", (date,))
                rows = cur.fetchall()
                cols = [desc[0] for desc in cur.description]
        return {"columns": cols, "rows": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
