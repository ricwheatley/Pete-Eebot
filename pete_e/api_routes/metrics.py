import time

import fastapi
from fastapi import Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from pete_e.application.exceptions import ApplicationError
from pete_e.api_routes.dependencies import get_metrics_service, validate_api_key

router = fastapi.APIRouter() if hasattr(fastapi, "APIRouter") else fastapi.FastAPI()


@router.get("/metrics_overview")
def metrics_overview(request: Request, date: str = Query(...), x_api_key: str = Header(None)):
    validate_api_key(request, x_api_key)
    try:
        return get_metrics_service().overview(date)
    except ApplicationError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/daily_summary")
def daily_summary(request: Request, date: str = Query(...), x_api_key: str = Header(None)):
    validate_api_key(request, x_api_key)
    try:
        return get_metrics_service().daily_summary(date)
    except ApplicationError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/recent_workouts")
def recent_workouts(
    request: Request,
    days: int = Query(14, ge=1, le=90),
    end_date: str | None = Query(None),
    x_api_key: str = Header(None),
):
    validate_api_key(request, x_api_key)
    try:
        return get_metrics_service().recent_workouts(days=days, iso_end_date=end_date)
    except ApplicationError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/coach_state")
def coach_state(
    request: Request,
    date: str = Query(...),
    profile: str | None = None,
    x_api_key: str = Header(None),
):
    validate_api_key(request, x_api_key)
    try:
        return get_metrics_service().coach_state(date, profile_slug=profile)
    except ApplicationError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/goal_state")
def goal_state(
    request: Request,
    profile: str | None = None,
    x_api_key: str = Header(None),
):
    validate_api_key(request, x_api_key)
    try:
        return get_metrics_service().goal_state(profile_slug=profile)
    except ApplicationError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/user_notes")
def user_notes(request: Request, days: int = Query(14, ge=1, le=90), x_api_key: str = Header(None)):
    validate_api_key(request, x_api_key)
    try:
        return get_metrics_service().user_notes(days=days)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/plan_context")
def plan_context(request: Request, date: str = Query(...), x_api_key: str = Header(None)):
    validate_api_key(request, x_api_key)
    try:
        return get_metrics_service().plan_context(date)
    except ApplicationError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/sse")
def sse(request: Request, x_api_key: str = Header(None)):
    validate_api_key(request, x_api_key)

    def event_generator():
        while True:
            yield f"data: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            time.sleep(5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
