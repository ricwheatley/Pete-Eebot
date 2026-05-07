import subprocess

import fastapi
from fastapi import Header, HTTPException, Query, Request

from pete_e.api_routes.dependencies import get_plan_service, validate_api_key
from pete_e.application.exceptions import ApplicationError

router = fastapi.APIRouter() if hasattr(fastapi, "APIRouter") else fastapi.FastAPI()


@router.get("/plan_for_day")
def plan_for_day(request: Request, date: str = Query(...), x_api_key: str = Header(None)):
    validate_api_key(request, x_api_key)
    try:
        return get_plan_service().for_day(date)
    except ApplicationError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/plan_for_week")
def plan_for_week(request: Request, start_date: str = Query(...), x_api_key: str = Header(None)):
    validate_api_key(request, x_api_key)
    try:
        return get_plan_service().for_week(start_date)
    except ApplicationError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.post("/run_pete_plan_async")
async def run_pete_plan_async(
    request: Request,
    weeks: int = Query(1),
    start_date: str = Query(...),
    x_api_key: str = Header(None),
):
    validate_api_key(request, x_api_key)
    subprocess.Popen(["pete", "plan", "--weeks", str(weeks), "--start-date", start_date])
    return {"status": "Started", "weeks": weeks, "start_date": start_date}
