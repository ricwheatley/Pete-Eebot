from fastapi import FastAPI, Query, HTTPException, Header, Request
from fastapi.responses import StreamingResponse
import psycopg
import time
from pete_e.config import settings  # loads .env via BaseSettings
from pete_e.infrastructure.db_conn import get_database_url

app = FastAPI(title="Pete-Eebot API")


# Helper to validate API key from header OR query string
def validate_api_key(request: Request, x_api_key: str | None) -> None:
    key = x_api_key or request.query_params.get("api_key")
    if key != settings.PETEEEBOT_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# Root endpoint - useful for connector validation
@app.get("/")
def root_get():
    return {"status": "ok", "message": "Pete-Eebot API root"}


@app.post("/")
def root_post(request: Request):
    return {"status": "ok", "message": "Pete-Eebot API root POST"}


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

    try:
        with psycopg.connect(get_database_url()) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM sp_metrics_overview(%s)", (date,))
                rows = cur.fetchall()
                cols = [desc[0] for desc in cur.description]

        return {"columns": cols, "rows": rows}

    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# SSE endpoint for streaming (demo)
@app.get("/sse")
def sse(request: Request, x_api_key: str = Header(None)):
    validate_api_key(request, x_api_key)

    def event_generator():
        while True:
            yield f"data: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            time.sleep(5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# Plan for a single day
@app.get("/plan_for_day")
def plan_for_day(
    request: Request,
    date: str = Query(..., description="Date in YYYY-MM-DD"),
    x_api_key: str = Header(None)
):
    """
    Run sp_plan_for_day(date) and return the scheduled workouts for that day.
    """
    validate_api_key(request, x_api_key)

    try:
        with psycopg.connect(get_database_url()) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM sp_plan_for_day(%s)", (date,))
                rows = cur.fetchall()
                cols = [desc[0] for desc in cur.description]
        return {"columns": cols, "rows": rows}
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Plan for a whole week
@app.get("/plan_for_week")
def plan_for_week(
    request: Request,
    start_date: str = Query(..., description="Start date of the week (YYYY-MM-DD)"),
    x_api_key: str = Header(None)
):
    """
    Run sp_plan_for_week(start_date) and return the scheduled workouts for that week.
    """
    validate_api_key(request, x_api_key)

    try:
        with psycopg.connect(get_database_url()) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM sp_plan_for_week(%s)", (start_date,))
                rows = cur.fetchall()
                cols = [desc[0] for desc in cur.description]
        return {"columns": cols, "rows": rows}
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
