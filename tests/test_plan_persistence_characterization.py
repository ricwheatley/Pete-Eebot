"""Characterization of the legacy ``PostgresDal.save_full_plan`` boundary."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, time
import inspect
from typing import Any, Iterator

import pytest
from psycopg.types.json import Json

from pete_e.domain.repositories import PlanRepository
from pete_e.infrastructure import plan_persistence, postgres_dal
from pete_e.infrastructure.postgres_dal import PostgresDal


class InjectedSqlFailure(RuntimeError):
    """Stable test exception raised by the recording cursor."""


class RecordingCursor:
    def __init__(
        self,
        returned_rows: list[tuple[object, ...] | None],
        *,
        fail_sql_containing: str | None = None,
    ) -> None:
        self.returned_rows = iter(returned_rows)
        self.fail_sql_containing = fail_sql_containing
        self.executions: list[tuple[str, object | None]] = []

    def __enter__(self) -> RecordingCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, params: object | None = None) -> None:
        statement = " ".join(query.split())
        self.executions.append((statement, params))
        if (
            self.fail_sql_containing is not None
            and self.fail_sql_containing in statement
        ):
            raise InjectedSqlFailure(statement)

    def fetchone(self) -> tuple[object, ...] | None:
        return next(self.returned_rows)


class RecordingConnection:
    def __init__(
        self,
        cursor: RecordingCursor,
        *,
        commit_error: Exception | None = None,
        cursor_error: Exception | None = None,
    ) -> None:
        self._autocommit = True
        self._cursor = cursor
        self._commit_error = commit_error
        self._cursor_error = cursor_error
        self.events: list[str] = []

    @property
    def autocommit(self) -> bool:
        return self._autocommit

    @autocommit.setter
    def autocommit(self, value: bool) -> None:
        self._autocommit = value
        self.events.append(f"autocommit={value}")

    def cursor(self, *, row_factory: object | None = None) -> RecordingCursor:
        assert row_factory is None
        self.events.append("cursor")
        if self._cursor_error is not None:
            raise self._cursor_error
        return self._cursor

    def commit(self) -> None:
        self.events.append("commit")
        if self._commit_error is not None:
            raise self._commit_error

    def rollback(self) -> None:
        self.events.append("rollback")


class RecordingPool:
    def __init__(self, connection: RecordingConnection) -> None:
        self._connection = connection
        self.closed = False
        self.connection_entries = 0

    @contextmanager
    def connection(self) -> Iterator[RecordingConnection]:
        self.connection_entries += 1
        yield self._connection


def _dal(
    returned_rows: list[tuple[object, ...] | None],
    *,
    fail_sql_containing: str | None = None,
    commit_error: Exception | None = None,
    cursor_error: Exception | None = None,
) -> tuple[PostgresDal, RecordingPool, RecordingConnection, RecordingCursor]:
    cursor = RecordingCursor(
        returned_rows,
        fail_sql_containing=fail_sql_containing,
    )
    connection = RecordingConnection(
        cursor,
        commit_error=commit_error,
        cursor_error=cursor_error,
    )
    pool = RecordingPool(connection)
    return PostgresDal(pool=pool), pool, connection, cursor  # type: ignore[arg-type]


def _minimal_plan(**overrides: object) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "start_date": date(2026, 8, 31),
        "weeks": 1,
        "plan_weeks": [{"week_number": 1, "workouts": []}],
    }
    payload.update(overrides)
    return payload


def _statements_containing(
    cursor: RecordingCursor,
    fragment: str,
) -> list[tuple[str, object | None]]:
    return [execution for execution in cursor.executions if fragment in execution[0]]


def test_repository_and_adapter_keep_the_save_contract() -> None:
    repository_signature = inspect.signature(PlanRepository.save_full_plan)
    adapter_signature = inspect.signature(PostgresDal.save_full_plan)

    assert tuple(repository_signature.parameters) == ("self", "plan_dict")
    assert tuple(adapter_signature.parameters) == ("self", "plan_dict")
    assert repository_signature.return_annotation == "int"
    assert adapter_signature.return_annotation == "int"


def test_success_preserves_raw_week_sort_workout_order_and_every_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dal, _, connection, cursor = _dal([(51,), (110,), (102,)])
    log_events: list[str] = []
    monkeypatch.setattr(
        postgres_dal.log_utils,
        "info",
        lambda message: (
            connection.events.append("log"),
            log_events.append(message),
        ),
    )
    strength_details = {
        "display_name": "Tempo squat",
        "nested": {"source": "characterization"},
    }
    cardio_details = {"session_type": "run", "distance_km": 8.5}
    comment_details = {"display_name": "Recovery notes"}
    payload = {
        "start_date": date(2026, 8, 31),
        "weeks": "use-list-length",
        "metadata": {"trace": ["a", "b"], "enabled": True},
        "plan_weeks": [
            {"week_number": "2", "is_test": True, "workouts": []},
            {
                "week_number": "10",
                "workouts": (
                    workout
                    for workout in [
                        {
                            "id": 999,
                            "day_of_week": "2",
                            "exercise_id": "73",
                            "exercise_name": "ignored by writer",
                            "sets": "5",
                            "reps": 3.9,
                            "rir": 2.5,
                            "rir_cue": 1.5,
                            "percent_1rm": 80.25,
                            "target_weight_kg": 92.5,
                            "scheduled_time": "07:05:06",
                            "slot": "22:00:00",
                            "is_cardio": False,
                            "type": "ignored",
                            "intensity": "ignored",
                            "comment": "first",
                            "optional": "false",
                            "recovery_focused": 0,
                            "details": strength_details,
                            "programmed_difficulty": "4",
                            "muscle_group": "ignored",
                        },
                        {
                            "day_of_week": True,
                            "exercise_id": None,
                            "sets": 1,
                            "reps": 1,
                            "rir": None,
                            "percent_1rm": None,
                            "target_weight_kg": None,
                            "scheduled_time": "not-a-time",
                            "slot": "18:30",
                            "is_cardio": 1,
                            "comment": "second",
                            "optional": False,
                            "recovery_focused": True,
                            "details": cardio_details,
                            "programmed_difficulty": "invalid",
                        },
                        {
                            "day_of_week": 7,
                            "exercise_id": object(),
                            "sets": 0,
                            "reps": 0,
                            "rir_cue": 3,
                            "scheduled_time": "",
                            "slot": "also-invalid",
                            "comment": "third",
                            "details": comment_details,
                        },
                    ]
                ),
            },
        ],
    }

    assert dal.save_full_plan(payload) == 51

    plan_insert = _statements_containing(cursor, "INSERT INTO training_plans")
    assert len(plan_insert) == 1
    plan_params = plan_insert[0][1]
    assert isinstance(plan_params, tuple)
    assert plan_params[:2] == (date(2026, 8, 31), 2)
    assert isinstance(plan_params[2], Json)
    assert plan_params[2].obj == payload["metadata"]

    week_inserts = _statements_containing(cursor, "INSERT INTO training_plan_weeks")
    assert [execution[1] for execution in week_inserts] == [
        (51, 10, False),
        (51, 2, True),
    ]

    workout_inserts = _statements_containing(
        cursor,
        "INSERT INTO training_plan_workouts",
    )
    assert len(workout_inserts) == 3
    first = workout_inserts[0][1]
    second = workout_inserts[1][1]
    third = workout_inserts[2][1]
    assert isinstance(first, tuple)
    assert isinstance(second, tuple)
    assert isinstance(third, tuple)
    assert first[:16] == (
        110,
        2,
        73,
        5,
        5,
        3,
        2.5,
        2.5,
        80.25,
        92.5,
        1.5,
        time(7, 5, 6),
        False,
        "first",
        True,
        False,
    )
    assert isinstance(first[16], Json)
    assert first[16].obj == strength_details
    assert first[17] == 4
    assert second[:16] == (
        110,
        1,
        None,
        1,
        1,
        1,
        None,
        None,
        None,
        None,
        None,
        time(18, 30),
        True,
        "second",
        False,
        True,
    )
    assert isinstance(second[16], Json)
    assert second[16].obj == cardio_details
    assert second[17] is None
    assert third[:16] == (
        110,
        7,
        None,
        0,
        0,
        0,
        None,
        None,
        None,
        None,
        3,
        None,
        False,
        "third",
        False,
        False,
    )
    assert isinstance(third[16], Json)
    assert third[16].obj == comment_details
    assert third[17] is None

    assert connection.events[:2] == ["cursor", "autocommit=False"]
    assert connection.events[-2:] == ["commit", "log"]
    assert "rollback" not in connection.events
    assert log_events == [
        "Persisted training plan 51 starting 2026-08-31 spanning 2 week(s)."
    ]


@pytest.mark.parametrize(
    ("payload", "error_type", "message"),
    [
        (None, TypeError, "plan_dict must be a mapping"),
        ([], TypeError, "plan_dict must be a mapping"),
        ({}, ValueError, "plan_dict must include a non-empty 'plan_weeks' list"),
        (
            {"plan_weeks": []},
            ValueError,
            "plan_dict must include a non-empty 'plan_weeks' list",
        ),
        (
            {"plan_weeks": ({"week_number": 1},), "start_date": date(2026, 1, 1)},
            ValueError,
            "plan_dict must include a non-empty 'plan_weeks' list",
        ),
        (
            {"plan_weeks": [{"week_number": 1}]},
            ValueError,
            "plan_dict must include a 'start_date'",
        ),
    ],
)
def test_outer_validation_happens_before_connection_acquisition(
    payload: object,
    error_type: type[Exception],
    message: str,
) -> None:
    dal, pool, connection, _ = _dal([])

    with pytest.raises(error_type, match=message):
        dal.save_full_plan(payload)  # type: ignore[arg-type]

    assert pool.connection_entries == 0
    assert connection.events == []


@pytest.mark.parametrize(
    ("plan_week", "error_type", "message"),
    [
        (3, AttributeError, "has no attribute 'get'"),
        ({"workouts": []}, ValueError, "week payload missing week_number"),
        (
            {"week_number": "invalid", "workouts": []},
            ValueError,
            "week payload missing week_number",
        ),
        (
            {"week_number": 1, "workouts": [[]]},
            TypeError,
            "workouts must be mappings",
        ),
        (
            {"week_number": 1, "workouts": [{}]},
            ValueError,
            "workout payload missing day_of_week",
        ),
        (
            {"week_number": 1, "workouts": 1},
            TypeError,
            "'int' object is not iterable",
        ),
    ],
)
def test_invalid_nested_payloads_re_raise_the_existing_exception(
    plan_week: object,
    error_type: type[Exception],
    message: str,
) -> None:
    dal, _, _, _ = _dal([(1,), (2,)])

    with pytest.raises(error_type, match=message):
        dal.save_full_plan(_minimal_plan(plan_weeks=[plan_week]))


@pytest.mark.parametrize("workouts", [None, [], "", 0, False])
def test_falsey_workout_containers_are_treated_as_empty(workouts: object) -> None:
    dal, _, connection, cursor = _dal([(1,), (2,)])

    assert (
        dal.save_full_plan(
            _minimal_plan(plan_weeks=[{"week_number": 1, "workouts": workouts}])
        )
        == 1
    )

    assert not _statements_containing(cursor, "INSERT INTO training_plan_workouts")
    assert connection.events[-1] == "commit"


def test_bool_week_count_is_retained_because_bool_is_an_int() -> None:
    dal, _, _, cursor = _dal([(1,), (2,)])

    assert dal.save_full_plan(_minimal_plan(weeks=False)) == 1

    plan_params = _statements_containing(cursor, "INSERT INTO training_plans")[0][1]
    assert isinstance(plan_params, tuple)
    assert plan_params[1] is False


def test_normal_save_executes_dml_only() -> None:
    dal, _, _, cursor = _dal([(1,), (2,)])

    dal.save_full_plan(_minimal_plan())

    statements = [statement for statement, _ in cursor.executions]
    assert statements[0].startswith("UPDATE training_plans SET is_active = false")
    assert all(
        not statement.startswith(("CREATE", "ALTER", "DROP"))
        for statement in statements
    )


@pytest.mark.parametrize(
    "fail_sql_containing",
    [
        "INSERT INTO training_plans",
        "INSERT INTO training_plan_weeks",
        "INSERT INTO training_plan_workouts",
    ],
)
def test_sql_failure_rolls_back_and_re_raises(
    fail_sql_containing: str,
) -> None:
    error = InjectedSqlFailure
    dal, _, connection, _ = _dal(
        [(1,), (2,)],
        fail_sql_containing=fail_sql_containing,
    )
    payload = _minimal_plan(
        plan_weeks=[{"week_number": 1, "workouts": [{"day_of_week": 1, "sets": 1}]}]
    )

    with pytest.raises(error):
        dal.save_full_plan(payload)

    assert connection.events[-1] == "rollback"
    assert "commit" not in connection.events


def test_json_wrapper_failure_rolls_back_and_re_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = object()
    original_json = plan_persistence.Json

    def raising_json(value: object) -> Json:
        if value is sentinel:
            raise TypeError("injected JSON failure")
        return original_json(value)

    monkeypatch.setattr(plan_persistence, "Json", raising_json)
    dal, _, connection, _ = _dal([(1,), (2,)])

    with pytest.raises(TypeError, match="injected JSON failure"):
        dal.save_full_plan(_minimal_plan(metadata=sentinel))

    assert connection.events[-1] == "rollback"
    assert "commit" not in connection.events


def test_missing_plan_return_id_rolls_back_and_re_raises() -> None:
    dal, _, connection, _ = _dal([None])

    with pytest.raises(TypeError, match="not subscriptable"):
        dal.save_full_plan(_minimal_plan())

    assert connection.events[-1] == "rollback"


def test_missing_week_return_id_rolls_back_and_re_raises() -> None:
    dal, _, connection, _ = _dal([(1,), None])

    with pytest.raises(TypeError, match="not subscriptable"):
        dal.save_full_plan(_minimal_plan())

    assert connection.events[-1] == "rollback"


def test_commit_failure_rolls_back_and_re_raises_same_exception() -> None:
    commit_error = RuntimeError("injected commit failure")
    dal, _, connection, _ = _dal([(1,), (2,)], commit_error=commit_error)

    with pytest.raises(RuntimeError) as caught:
        dal.save_full_plan(_minimal_plan())

    assert caught.value is commit_error
    assert connection.events[-2:] == ["commit", "rollback"]


def test_cursor_acquisition_failure_is_re_raised_before_transaction_try() -> None:
    cursor_error = RuntimeError("injected cursor failure")
    dal, _, connection, _ = _dal([], cursor_error=cursor_error)

    with pytest.raises(RuntimeError) as caught:
        dal.save_full_plan(_minimal_plan())

    assert caught.value is cursor_error
    assert connection.events == ["cursor"]
