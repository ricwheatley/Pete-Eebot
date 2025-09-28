from fastapi import FastAPI, Query, HTTPException, Header, Request
from fastapi.responses import StreamingResponse
import psycopg
import time
from pete_e.config import settings  # loads .env via BaseSettings

app = FastAPI(title="Pete-Eebot API")

# Helper to validate API key from header OR query string
def validate_api_key(request: Request, x_api_key: str | None) -> None:
    key = x_api_key or request.query_params.get("api_key")
    if key != settings.PETEEEBOT_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

# Root endpoint - required for connector validation
@app.get("/")
def root():
    return {"status": "ok", "message": "Pete-Eebot API root"}

# Metrics endpoint
@app.get("/metrics_overview")
def metrics_overview(
    request: Request,
    date: str = Query(..., description="Date in YYYY-MM-DD"),
    x_api_key: str = Header(None)
):
    """
    Run sp_metrics_overview(date) and return columns + rows as JSON.
    Requires API key in header (X-API-Key) or query string (?api_key=).
    """
    validate_api_key(request, x_api_key)

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

# SSE endpoint for streaming
@app.get("/sse")
def sse(request: Request, x_api_key: str = Header(None)):
    """
    Simple SSE endpoint that streams a timestamp every 5 seconds.
    Requires API key in header (X-API-Key) or query string (?api_key=).
    """
    validate_api_key(request, x_api_key)

    def event_generator():
        while True:
            yield f"data: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            time.sleep(5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
