from fastapi import FastAPI, Query, HTTPException, Header, Request
from fastapi.responses import StreamingResponse
import psycopg
import time
import datetime
import hmac
import hashlib
import subprocess
from pete_e.config import settings  # loads .env via BaseSettings
from pete_e.infrastructure.db_conn import get_database_url
from pete_e.cli.status import (
    DEFAULT_TIMEOUT_SECONDS,
    render_results,
    run_status_checks,
)
from pete_e.application.sync import run_sync_with_retries

app = FastAPI(title="Pete-Eebot API")
WEBHOOK_SECRET = b"supersecretwebhooktoken"

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


@app.get("/status")
def status(
    request: Request,
    x_api_key: str = Header(None),
    timeout: float = Query(
        DEFAULT_TIMEOUT_SECONDS,
        ge=0.1,
        description="Per dependency timeout in seconds.",
    ),
):
    """Expose the CLI health check results via the API."""

    validate_api_key(request, x_api_key)

    try:
        results = run_status_checks(timeout=timeout)
    except Exception as exc:  # pragma: no cover - defensive response
        raise HTTPException(status_code=500, detail=str(exc))

    checks = [
        {"name": result.name, "ok": result.ok, "detail": result.detail}
        for result in results
    ]
    overall_ok = all(result["ok"] for result in checks)

    return {
        "ok": overall_ok,
        "checks": checks,
        "summary": render_results(results),
    }


@app.post("/sync")
def sync(
    request: Request,
    x_api_key: str = Header(None),
    days: int = Query(7, ge=1, description="Number of past days to include."),
    retries: int = Query(3, ge=0, description="Number of retries on failure."),
):
    """Trigger the same sync workflow exposed via the CLI."""

    validate_api_key(request, x_api_key)

    try:
        result = run_sync_with_retries(days=days, retries=retries)
    except Exception as exc:  # pragma: no cover - defensive response
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "success": result.success,
        "attempts": result.attempts,
        "failed_sources": result.failed_sources,
        "source_statuses": result.source_statuses,
        "undelivered_alerts": result.undelivered_alerts,
        "label": result.label,
        "summary": result.summary_line(days=days),
    }


@app.get("/logs")
def logs(
    request: Request,
    x_api_key: str = Header(None),
    lines: int = Query(50, ge=1, le=1000, description="Number of log lines to return."),
):
    """Return the last ``lines`` entries from the Pete-Eebot history log."""

    validate_api_key(request, x_api_key)

    log_path = settings.log_path
    if not log_path.exists():
        raise HTTPException(status_code=404, detail=f"Log file not found: {log_path}")

    try:
        with log_path.open("r", encoding="utf-8") as log_file:
            log_lines = log_file.readlines()
    except Exception as exc:  # pragma: no cover - defensive response
        raise HTTPException(status_code=500, detail=str(exc))

    tail = [line.rstrip("\n") for line in log_lines[-lines:]]

    return {"path": str(log_path), "lines": tail}

@app.post("/run_pete_plan_async")
async def run_pete_plan_async(
    request: Request,
    weeks: int = Query(1),
    start_date: str = Query(...),
    x_api_key: str = Header(None),
):
    validate_api_key(request, x_api_key)
    subprocess.Popen(["pete", "plan", "--weeks", str(weeks), "--start-date", start_date])
    return {"status": "Started", "weeks": weeks, "start_date": start_date}


@app.post("/webhook")
async def github_webhook(request: Request):
    """
    GitHub push webhook. Validates signature, then triggers deploy.sh asynchronously.
    """
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    if not signature:
        raise HTTPException(status_code=403, detail="Missing signature")

    try:
        sha_name, sig = signature.split("=")
    except ValueError:
        raise HTTPException(status_code=403, detail="Bad signature format")

    if sha_name != "sha256":
        raise HTTPException(status_code=403, detail="Unsupported signature type")

    import hmac, hashlib
    mac = hmac.new(WEBHOOK_SECRET, msg=body, digestmod=hashlib.sha256)
    if not hmac.compare_digest(mac.hexdigest(), sig):
        raise HTTPException(status_code=403, detail="Invalid signature")

    # Run deploy.sh in the background, don't block response
    subprocess.Popen(["/home/ricwheatley/pete-eebot/deploy.sh"])

    return {
        "status": "Deployment triggered",
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z"
    }