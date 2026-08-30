from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from pete_e import api
from pete_e.api_routes import dependencies, metrics, nutrition, plan


pytestmark = pytest.mark.contract


def _s02_sentinel(*parts: str) -> str:
    return "-".join(("s02", "generated", *parts))


class _MetricsServiceFake:
    def overview(self, date: str):
        return {"columns": ["date", "value"], "rows": [[date, 42]]}


class _PlanServiceFake:
    def for_day(self, date: str):
        return {"columns": ["date", "session"], "rows": [[date, "A"]]}


class _NutritionServiceFake:
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

    def update_log(self, log_id: int, payload):
        return {
            "id": log_id,
            "protein_g": 10,
            "carbs_g": 20,
            "fat_g": 5,
            "alcohol_g": payload.get("alcohol_g", 0),
            "estimated_total_calories": payload.get("estimated_total_calories"),
            "calories_est": payload.get("estimated_total_calories", 165),
            "duplicate": False,
            "warnings": [],
        }

    def daily_summary(self, date: str):
        return {
            "date": date,
            "total_protein_g": 145,
            "total_carbs_g": 210,
            "total_fat_g": 65,
            "total_alcohol_g": 12,
            "total_fiber_g": 18,
            "total_estimated_calories": 2005,
            "meals_logged": 4,
        }


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        dependencies.settings,
        "PETEEEBOT_API_KEY",
        SecretStr("test-key"),
    )
    with TestClient(api.app) as test_client:
        yield test_client


def _auth_headers() -> dict[str, str]:
    return {"X-API-Key": "test-key"}


def test_api_key_failure_does_not_expose_configured_or_supplied_secret(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = _s02_sentinel("configured", "api", "key")
    supplied = _s02_sentinel("supplied", "api", "key")
    monkeypatch.setattr(
        dependencies.settings,
        "PETEEEBOT_API_KEY",
        SecretStr(configured),
    )

    response = client.get(
        "/api/v1/status",
        headers={"X-API-Key": supplied},
    )

    assert response.status_code == 401
    assert configured not in response.text
    assert supplied not in response.text


def test_missing_api_key_configuration_preserves_safe_503_contract(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supplied = _s02_sentinel("supplied", "api", "key")
    monkeypatch.setattr(dependencies.settings, "PETEEEBOT_API_KEY", None)

    response = client.get(
        "/api/v1/status",
        headers={"X-API-Key": supplied},
    )

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "service_unavailable"
    assert error["message"] == "PETEEEBOT_API_KEY is not configured"
    assert supplied not in response.text


def test_api_v1_mounts_key_read_routes():
    schema = api.app.openapi()
    mounted_routes = {
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        for method in operations
        if method != "parameters"
    }

    key_read_paths = [
        "/metrics_overview",
        "/daily_summary",
        "/recent_workouts",
        "/coach_state",
        "/goal_state",
        "/user_notes",
        "/plan_context",
        "/nutrition/daily-summary",
        "/plan_for_day",
        "/plan_for_week",
        "/plan_decision_trace",
        "/status",
        "/logs",
    ]

    for path in key_read_paths:
        assert ("GET", f"{api.API_V1_PREFIX}{path}") in mounted_routes


def test_legacy_routes_remain_mounted_during_v1_transition():
    schema = api.app.openapi()
    mounted_routes = {
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        for method in operations
        if method != "parameters"
    }

    assert ("GET", "/metrics_overview") in mounted_routes
    assert ("GET", "/plan_for_day") in mounted_routes
    assert ("GET", "/nutrition/daily-summary") in mounted_routes


def test_metrics_overview_contract_shape(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(metrics, "get_metrics_service", lambda: _MetricsServiceFake())

    response = client.get(
        "/api/v1/metrics_overview",
        params={"date": "2024-01-01"},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "columns": ["date", "value"],
        "rows": [["2024-01-01", 42]],
    }


def test_plan_for_day_contract_and_auth(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(plan, "get_plan_service", lambda: _PlanServiceFake())

    response = client.get(
        "/api/v1/plan_for_day",
        params={"date": "2024-02-02"},
        headers=_auth_headers(),
    )
    unauthorized = client.get(
        "/api/v1/plan_for_day",
        params={"date": "2024-02-02"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "columns": ["date", "session"],
        "rows": [["2024-02-02", "A"]],
    }
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "unauthorized"


def test_required_query_parameter_uses_fastapi_validation(client: TestClient):
    response = client.get("/api/v1/metrics_overview", headers=_auth_headers())

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_nutrition_log_macros_contract(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(nutrition, "get_nutrition_service", lambda: _NutritionServiceFake())
    monkeypatch.setattr(nutrition, "enforce_command_rate_limit", lambda *_args, **_kwargs: None)

    response = client.post(
        "/api/v1/nutrition/log-macros",
        json={"protein_g": 40, "carbs_g": 65, "fat_g": 18},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["id"] == 1
    assert response.json()["calories_est"] == 582
    assert response.json()["duplicate"] is False


def test_nutrition_daily_summary_contract(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(nutrition, "get_nutrition_service", lambda: _NutritionServiceFake())

    response = client.get(
        "/api/v1/nutrition/daily-summary",
        params={"date": "2026-05-05"},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["date"] == "2026-05-05"
    assert response.json()["meals_logged"] == 4


def test_nutrition_patch_contract(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(nutrition, "get_nutrition_service", lambda: _NutritionServiceFake())
    monkeypatch.setattr(nutrition, "enforce_command_rate_limit", lambda *_args, **_kwargs: None)

    response = client.patch(
        "/api/v1/nutrition/log-macros/6",
        json={"alcohol_g": 18, "estimated_total_calories": 150},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["id"] == 6
    assert response.json()["calories_est"] == 150
