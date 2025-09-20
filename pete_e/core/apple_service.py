"""FastAPI service to receive Apple Health summaries."""

import secrets
from datetime import datetime

from fastapi import FastAPI, HTTPException, Header, status

# Assuming DAL is in this structure
from pete_e.config import settings
from pete_e.infrastructure.postgres_dal import PostgresDal
from pete_e.infrastructure import log_utils

app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "Pete-Eebot Apple Service is running."}

@app.post("/summary")
def receive_summary(payload: dict, x_apple_webhook_token: str = Header(default=None)):
    """
    Receives a daily summary payload and saves it to the database.
    Payload should be a JSON object with a 'date' key (YYYY-MM-DD)
    and other Apple Health metrics.
    """
    expected_token = settings.APPLE_WEBHOOK_TOKEN
    if not expected_token:
        log_utils.log_message("APPLE_WEBHOOK_TOKEN not configured; rejecting request.", "ERROR")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Apple webhook token not configured.",
        )

    if not x_apple_webhook_token or not secrets.compare_digest(x_apple_webhook_token, expected_token):
        log_utils.log_message("Rejected Apple payload due to invalid authentication token.", "WARNING")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
        )

    log_utils.log_message(f"Received Apple Health payload: {payload.get('date')}", "INFO")
    if not payload or not payload.get("date"):
        raise HTTPException(status_code=400, detail="Payload missing or date field not found.")

    dal = PostgresDal()
    try:
        target_date = datetime.strptime(payload.get("date"), "%Y-%m-%d").date()
        
        # Call the correct source-specific save method
        dal.save_apple_daily(target_date, payload)
        
        return {"status": "ok", "message": "Apple data saved."}
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    except Exception as e:
        log_utils.log_message(f"Failed to process Apple payload: {e}", "ERROR")
        raise HTTPException(status_code=500, detail="Internal server error.")

