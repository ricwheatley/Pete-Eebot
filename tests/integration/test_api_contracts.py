from __future__ import annotations

import sys
import types

if "fastapi" not in sys.modules:
    fastapi_module = types.ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: str | None = None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class Request:
        def __init__(self, query_params: dict | None = None):
            self.query_params = query_params or {}

    def _identity(value=None, **kwargs):
        return value

    class APIRouter:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def post(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def include_router(self, *args, **kwargs):
            return None

    fastapi_module.APIRouter = APIRouter
    fastapi_module.FastAPI = APIRouter
    fastapi_module.Query = _identity
    fastapi_module.Header = _identity
    fastapi_module.HTTPException = HTTPException
    fastapi_module.Request = Request

    responses_module = types.ModuleType("fastapi.responses")
    responses_module.StreamingResponse = object

    sys.modules["fastapi"] = fastapi_module
    sys.modules["fastapi.responses"] = responses_module

from pete_e.api_routes import dependencies, metrics, nutrition, plan


class _StubMetricsService:
    def overview(self, date: str):
        return {"columns": ["date", "value"], "rows": [[date, 42]]}


class _StubPlanService:
    def for_day(self, date: str):
        return {"columns": ["date", "session"], "rows": [[date, "A"]]}


class _StubNutritionService:
    def log_macros(self, payload):
        return {
            "id": 1,
            "protein_g": payload["protein_g"],
            "carbs_g": payload["carbs_g"],
            "fat_g": payload["fat_g"],
            "calories_est": 582,
            "duplicate": False,
            "warnings": [],
        }

    def daily_summary(self, date: str):
        return {
            "date": date,
            "protein_g": 145,
            "carbs_g": 210,
            "fat_g": 65,
            "calories_est": 2005,
            "meals_logged": 4,
        }


def test_metrics_overview_contract_shape(monkeypatch):
    monkeypatch.setattr(dependencies.settings, "PETEEEBOT_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(metrics, "get_metrics_service", lambda: _StubMetricsService())

    payload = metrics.metrics_overview(
        request=metrics.Request({}),
        date="2024-01-01",
        x_api_key="test-key",
    )

    assert set(payload.keys()) == {"columns", "rows"}
    assert payload["columns"] == ["date", "value"]


def test_plan_for_day_contract_and_auth(monkeypatch):
    monkeypatch.setattr(dependencies.settings, "PETEEEBOT_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(plan, "get_plan_service", lambda: _StubPlanService())

    with_auth = plan.plan_for_day(
        request=plan.Request({}),
        date="2024-02-02",
        x_api_key="test-key",
    )

    assert set(with_auth.keys()) == {"columns", "rows"}
    assert with_auth["rows"] == [["2024-02-02", "A"]]


def test_nutrition_log_macros_contract(monkeypatch):
    monkeypatch.setattr(dependencies.settings, "PETEEEBOT_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(nutrition, "get_nutrition_service", lambda: _StubNutritionService())

    payload = nutrition.log_macros(
        request=nutrition.Request({}),
        payload={"protein_g": 40, "carbs_g": 65, "fat_g": 18},
        x_api_key="test-key",
    )

    assert payload["id"] == 1
    assert payload["calories_est"] == 582
    assert payload["duplicate"] is False


def test_nutrition_daily_summary_contract(monkeypatch):
    monkeypatch.setattr(dependencies.settings, "PETEEEBOT_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(nutrition, "get_nutrition_service", lambda: _StubNutritionService())

    payload = nutrition.nutrition_daily_summary(
        request=nutrition.Request({}),
        date="2026-05-05",
        x_api_key="test-key",
    )

    assert payload["date"] == "2026-05-05"
    assert payload["meals_logged"] == 4
