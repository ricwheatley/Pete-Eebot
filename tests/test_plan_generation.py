from __future__ import annotations

from contextlib import contextmanager
from datetime import date

import tests.config_stub  # noqa: F401

from pete_e.application.plan_generation import PlanGenerationService


def test_plan_generation_service_holds_lock(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    class StubDal:
        @contextmanager
        def hold_plan_generation_lock(self):
            calls.append(("lock_enter", None))
            try:
                yield
            finally:
                calls.append(("lock_exit", None))

        def close(self) -> None:
            calls.append(("close", None))

    class StubWgerClient:
        pass

    class StubPlanService:
        def __init__(self, dal):
            assert isinstance(dal, StubDal)

        def create_next_plan_for_cycle(self, *, start_date: date) -> int:
            calls.append(("create", start_date))
            return 42

    class StubExportService:
        def __init__(self, dal, wger_client):
            assert isinstance(dal, StubDal)
            assert isinstance(wger_client, StubWgerClient)

        def export_plan_week(
            self,
            *,
            plan_id: int,
            week_number: int,
            start_date: date,
            force_overwrite: bool = False,
            dry_run: bool = False,
        ):
            calls.append(
                ("export", (plan_id, week_number, start_date, force_overwrite, dry_run))
            )
            return {"status": "exported"}

    monkeypatch.setattr("pete_e.application.plan_generation.PlanService", StubPlanService)
    monkeypatch.setattr(
        "pete_e.application.plan_generation.WgerExportService",
        StubExportService,
    )

    service = PlanGenerationService(
        dal_factory=StubDal,
        wger_client_factory=StubWgerClient,
    )

    plan_id = service.run(start_date=date(2024, 5, 6), dry_run=True)

    assert plan_id == 42
    assert calls == [
        ("lock_enter", None),
        ("create", date(2024, 5, 6)),
        ("export", (42, 1, date(2024, 5, 6), True, True)),
        ("lock_exit", None),
        ("close", None),
    ]
