from __future__ import annotations

from typing import Any

import fastapi
from fastapi import Header, HTTPException, Query, Request

from pete_e.api_routes.dependencies import (
    enforce_command_rate_limit,
    get_nutrition_service,
    validate_api_key,
)
from pete_e.application.exceptions import ApplicationError
from pete_e.domain.auth import ROLE_OPERATOR

router = fastapi.APIRouter() if hasattr(fastapi, "APIRouter") else fastapi.FastAPI()


def _raise_http(exc: ApplicationError) -> None:
    raise HTTPException(status_code=exc.http_status, detail=exc.message)


@router.post("/nutrition/log-macros")
def log_macros(
    request: Request,
    payload: dict[str, Any] | None = None,
    x_api_key: str = Header(None),
):
    validate_api_key(request, x_api_key, required_session_role=ROLE_OPERATOR)
    enforce_command_rate_limit(request, "nutrition_log")
    try:
        return get_nutrition_service().log_macros(payload or {})
    except ApplicationError as exc:
        _raise_http(exc)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.patch("/nutrition/log-macros/{log_id}")
def update_nutrition_log(
    log_id: int,
    request: Request,
    payload: dict[str, Any] | None = None,
    x_api_key: str = Header(None),
):
    validate_api_key(request, x_api_key, required_session_role=ROLE_OPERATOR)
    enforce_command_rate_limit(request, "nutrition_update")
    try:
        return get_nutrition_service().update_log(log_id, payload or {})
    except ApplicationError as exc:
        _raise_http(exc)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/nutrition/daily-summary")
def nutrition_daily_summary(
    request: Request,
    date: str = Query(...),
    x_api_key: str = Header(None),
):
    validate_api_key(request, x_api_key)
    try:
        return get_nutrition_service().daily_summary(date)
    except ApplicationError as exc:
        _raise_http(exc)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Internal server error") from exc

