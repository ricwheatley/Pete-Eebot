from __future__ import annotations

from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pete_e.application.exceptions import ConflictError, NotFoundError, ValidationError
from pete_e.application.services import WgerExportService
from pete_e.application.wger_week_replacement import WgerWeekReplacementService
from pete_e.domain import schedule_rules


class _StoredWeekDal:
    def __init__(self, *, reference: dict | None = None, rows: list[dict] | None = None) -> None:
        self.reference = reference
        self.rows = rows if rows is not None else []
        self.recorded: list[dict] = []
        self.reference_calls: list[date] = []
        self.row_calls: list[tuple[int, int]] = []

    def get_plan_week_reference(self, week_start: date):
        self.reference_calls.append(week_start)
        return self.reference

    def get_plan_week_rows(self, plan_id: int, week_number: int):
        self.row_calls.append((plan_id, week_number))
        return self.rows

    def get_plan_decision_trace(self, plan_id: int, week_number: int):
        return []

    def record_wger_export(self, plan_id, week_number, payload, response=None, routine_id=None):
        self.recorded.append(
            {
                "plan_id": plan_id,
                "week_number": week_number,
                "payload": payload,
                "response": response,
                "routine_id": routine_id,
            }
        )

    def save_full_plan(self, *_args, **_kwargs):
        raise AssertionError("replacement must not save or replace a plan")

    def update_workout_targets(self, *_args, **_kwargs):
        raise AssertionError("replacement must not adjust a plan")


class _WgerClient:
    base_url = "https://example.invalid"

    def __init__(self, *, existing: bool) -> None:
        self.existing = existing
        self.calls: list[tuple] = []
        self._next_id = 100

    def find_routine(self, name: str, start: date):
        self.calls.append(("find_routine", name, start))
        return {"id": 42, "name": name, "start": start.isoformat()} if self.existing else None

    def find_or_create_routine(self, **kwargs):
        self.calls.append(("find_or_create_routine", kwargs))
        return {"id": 43, "name": kwargs["name"], "start": kwargs["start"].isoformat()}

    def create_routine(self, **kwargs):
        self.calls.append(("create_routine", kwargs))
        return {"id": 43, "name": kwargs["name"], "start": kwargs["start"].isoformat()}

    def update_routine(self, routine_id: int, **kwargs):
        self.calls.append(("update_routine", routine_id, kwargs))
        return {"id": routine_id, **kwargs}

    def delete_routine(self, routine_id: int):
        self.calls.append(("delete_routine", routine_id))

    def delete_all_days_in_routine(self, routine_id: int):
        self.calls.append(("delete_all_days_in_routine", routine_id))

    def create_day(self, routine_id: int, order: int, name: str):
        self.calls.append(("create_day", routine_id, order, name))
        self._next_id += 1
        return {"id": self._next_id, "name": name}

    def create_slot(self, day_id: int, order: int, comment=None):
        self.calls.append(("create_slot", day_id, order, comment))
        self._next_id += 1
        return {"id": self._next_id}

    def create_slot_entry(self, slot_id: int, exercise_id: int, order: int = 1, **kwargs):
        self.calls.append(("create_slot_entry", slot_id, exercise_id, order, kwargs))
        self._next_id += 1
        return {"id": self._next_id}

    def set_config(self, config_type: str, slot_entry_id: int, iteration: int, value):
        self.calls.append(("set_config", config_type, slot_entry_id, iteration, value))


def _stored_row() -> dict:
    return {
        "id": 501,
        "week_number": 2,
        "is_test": False,
        "day_of_week": 1,
        "exercise_id": schedule_rules.BENCH_ID,
        "exercise_name": "Bench Press",
        "sets": 3,
        "reps": 5,
        "rir": 2.0,
        "percent_1rm": 80.0,
        "target_weight_kg": 82.5,
        "scheduled_time": "07:00:00",
        "is_cardio": False,
        "comment": None,
        "details": {},
    }


def _service(*, dal: _StoredWeekDal, client: _WgerClient) -> WgerWeekReplacementService:
    validation = SimpleNamespace(
        assess_plan=MagicMock(side_effect=AssertionError("replacement must not assess readiness")),
        apply_adjustment=MagicMock(side_effect=AssertionError("replacement must not adjust a plan")),
        validate_and_adjust_plan=MagicMock(
            side_effect=AssertionError("replacement must not validate or adjust a plan")
        ),
    )
    exporter = WgerExportService(
        dal=dal,
        wger_client=client,
        validation_service=validation,
    )
    return WgerWeekReplacementService(
        dal=dal,
        wger_client=client,
        export_service=exporter,
    )


def test_replacement_stages_then_promotes_unchanged_stored_rows() -> None:
    week_start = date(2026, 8, 24)
    rows = [_stored_row()]
    original_rows = deepcopy(rows)
    dal = _StoredWeekDal(
        reference={"plan_id": 17, "week_number": 2, "week_start": week_start},
        rows=rows,
    )
    client = _WgerClient(existing=True)

    result = _service(dal=dal, client=client).replace_week(week_start)

    assert result.plan_id == 17
    assert result.week_number == 2
    assert result.deleted_existing is True
    assert result.days_sent == 1
    assert rows == original_rows
    assert dal.reference_calls == [week_start]
    assert dal.row_calls == [(17, 2)]
    assert dal.recorded[0]["routine_id"] == 43
    assert dal.recorded[0]["response"]["replacement"] is True
    assert dal.recorded[0]["response"]["deleted_existing"] is True
    assert client.calls[0][0] == "find_routine"
    assert client.calls[1][0] == "create_routine"
    assert any(call[0] == "create_day" for call in client.calls)
    assert ("delete_routine", 42) in client.calls
    assert any(call[0] == "update_routine" and call[1] == 43 for call in client.calls)
    assert not any(call[0] == "find_or_create_routine" for call in client.calls)


def test_replacement_creates_and_sends_when_wger_week_is_absent_without_deleting() -> None:
    week_start = date(2026, 8, 24)
    dal = _StoredWeekDal(
        reference={"plan_id": 17, "week_number": 2, "week_start": week_start},
        rows=[_stored_row()],
    )
    client = _WgerClient(existing=False)

    result = _service(dal=dal, client=client).replace_week(week_start)

    assert result.deleted_existing is False
    assert result.routine_id == 43
    assert any(call[0] == "create_routine" for call in client.calls)
    assert any(call[0] == "update_routine" for call in client.calls)
    assert not any(call == ("delete_routine", 42) for call in client.calls)


def test_replacement_preserves_existing_routine_when_staging_write_fails() -> None:
    week_start = date(2026, 8, 24)
    dal = _StoredWeekDal(
        reference={"plan_id": 17, "week_number": 2, "week_start": week_start},
        rows=[_stored_row()],
    )
    client = _WgerClient(existing=True)

    def _fail_staging_write(routine_id: int, order: int, name: str):
        client.calls.append(("create_day", routine_id, order, name))
        raise RuntimeError("wger staging write failed")

    client.create_day = _fail_staging_write  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="staging write failed"):
        _service(dal=dal, client=client).replace_week(week_start)

    assert ("delete_routine", 43) in client.calls
    assert ("delete_routine", 42) not in client.calls
    assert not any(call[0] == "update_routine" for call in client.calls)
    assert dal.recorded == []


def test_replacement_refuses_to_touch_wger_without_an_exact_stored_week() -> None:
    week_start = date(2026, 8, 24)
    dal = _StoredWeekDal(reference=None)
    client = _WgerClient(existing=True)

    with pytest.raises(NotFoundError, match="No stored plan week"):
        _service(dal=dal, client=client).replace_week(week_start)

    assert client.calls == []
    assert dal.recorded == []


def test_replacement_refuses_to_delete_wger_for_an_empty_stored_week() -> None:
    week_start = date(2026, 8, 24)
    dal = _StoredWeekDal(
        reference={"plan_id": 17, "week_number": 2, "week_start": week_start},
        rows=[],
    )
    client = _WgerClient(existing=True)

    with pytest.raises(ConflictError, match="has no workout rows"):
        _service(dal=dal, client=client).replace_week(week_start)

    assert client.calls == []
    assert dal.recorded == []


def test_replacement_requires_a_monday_week_start() -> None:
    dal = _StoredWeekDal()
    client = _WgerClient(existing=True)

    with pytest.raises(ValidationError, match="must be a Monday"):
        _service(dal=dal, client=client).replace_week(date(2026, 8, 25))

    assert dal.reference_calls == []
    assert client.calls == []
