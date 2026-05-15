from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from pete_e.api_routes import dependencies, logs_webhooks, metrics, nutrition, plan, status_sync


def _request_with_query_api_key() -> dependencies.Request:
    return dependencies.Request({"api_key": "test-key"})


@pytest.fixture(autouse=True)
def enable_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dependencies.settings, "PETEEEBOT_API_KEY", "test-key", raising=False)


def test_validate_api_key_ignores_query_param_api_key() -> None:
    with pytest.raises(dependencies.HTTPException) as exc:
        dependencies.validate_api_key(_request_with_query_api_key(), x_api_key=None)

    assert exc.value.status_code == 401


def test_validate_api_key_accepts_header_even_when_query_param_is_wrong() -> None:
    request = dependencies.Request({"api_key": "wrong-key"})

    dependencies.validate_api_key(request, x_api_key="test-key")


@pytest.mark.parametrize(
    "call_route",
    [
        lambda request: metrics.metrics_overview(request=request, date="2026-05-15", x_api_key=None),
        lambda request: metrics.daily_summary(request=request, date="2026-05-15", x_api_key=None),
        lambda request: metrics.recent_workouts(request=request, days=14, end_date=None, x_api_key=None),
        lambda request: metrics.coach_state(request=request, date="2026-05-15", x_api_key=None),
        lambda request: metrics.goal_state(request=request, x_api_key=None),
        lambda request: metrics.user_notes(request=request, days=14, x_api_key=None),
        lambda request: metrics.plan_context(request=request, date="2026-05-15", x_api_key=None),
        lambda request: metrics.sse(request=request, x_api_key=None),
        lambda request: nutrition.nutrition_daily_summary(request=request, date="2026-05-15", x_api_key=None),
        lambda request: nutrition.log_macros(request=request, payload={"protein_g": 1}, x_api_key=None),
        lambda request: nutrition.update_nutrition_log(log_id=1, request=request, payload={}, x_api_key=None),
        lambda request: plan.plan_for_day(request=request, date="2026-05-15", x_api_key=None),
        lambda request: plan.plan_for_week(request=request, start_date="2026-05-11", x_api_key=None),
        lambda request: plan.plan_decision_trace(request=request, plan_id=1, week_number=1, x_api_key=None),
        lambda request: status_sync.status(request=request, x_api_key=None, timeout=1.0),
        lambda request: status_sync.sync(request=request, x_api_key=None, days=1, retries=0),
        lambda request: logs_webhooks.logs(request=request, x_api_key=None, lines=1),
    ],
)
def test_api_key_routes_reject_query_param_auth(call_route: Callable[[dependencies.Request], object]) -> None:
    with pytest.raises(dependencies.HTTPException) as exc:
        call_route(_request_with_query_api_key())

    assert exc.value.status_code == 401


def test_plan_command_route_rejects_query_param_auth() -> None:
    async def _call() -> object:
        return await plan.run_pete_plan_async(
            request=_request_with_query_api_key(),
            weeks=1,
            start_date="2026-05-15",
            x_api_key=None,
        )

    with pytest.raises(dependencies.HTTPException) as exc:
        asyncio.run(_call())

    assert exc.value.status_code == 401
