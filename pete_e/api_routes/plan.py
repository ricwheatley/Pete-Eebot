import fastapi
from fastapi import Header, HTTPException, Query, Request

from pete_e.api_routes.dependencies import (
    DEFAULT_PROCESS_TIMEOUT_SECONDS,
    enforce_command_rate_limit,
    get_plan_service,
    start_guarded_high_risk_process,
    validate_api_key,
)
from pete_e.application.exceptions import ApplicationError
from pete_e.domain.auth import ROLE_OPERATOR

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


@router.get("/plan_decision_trace")
def plan_decision_trace(
    request: Request,
    plan_id: int = Query(..., ge=1),
    week_number: int = Query(..., ge=1),
    x_api_key: str = Header(None),
):
    validate_api_key(request, x_api_key)
    try:
        return get_plan_service().decision_trace(plan_id=plan_id, week_number=week_number)
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
    timeout: float = Query(DEFAULT_PROCESS_TIMEOUT_SECONDS, ge=30, le=3600),
):
    validate_api_key(request, x_api_key, required_session_role=ROLE_OPERATOR)
    enforce_command_rate_limit(request, "plan")
    start_guarded_high_risk_process(
        "plan",
        ["pete", "plan", "--weeks", str(weeks), "--start-date", start_date],
        timeout_seconds=timeout,
    )
    return {"status": "Started", "weeks": weeks, "start_date": start_date}
