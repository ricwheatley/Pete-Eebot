"""
FastAPI service to receive Apple Health summaries.
"""
from fastapi import FastAPI, HTTPException
from datetime import datetime

# Assuming DAL and close_pool are in this structure
from pete_e.data_access.postgres_dal import PostgresDal, close_pool
from pete_e.infra import log_utils

app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "Pete-Eebot Apple Service is running."}

@app.post("/summary")
def receive_summary(payload: dict):
    """
    Receives a daily summary payload and saves it to the database.
    Payload should be a JSON object with a 'date' key (YYYY-MM-DD)
    and other Apple Health metrics.
    """
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
    finally:
        # This block ensures the pool is closed even if an error occurs
        close_pool()