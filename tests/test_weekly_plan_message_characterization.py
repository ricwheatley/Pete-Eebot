"""Characterization of the legacy weekly-plan CLI-owned application path."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from pete_e.application import api_services
from pete_e.cli import messenger


TARGET = date(2024, 9, 9)


class _Renderer:
    def __init__(self, response: object = "rendered weekly plan") -> None:
        self.response = response
        self.calls: list[tuple[object, int, date | None]] = []

    def build_weekly_plan(
        self,
        rows: object,
        week_number: int,
        week_start: date | None = None,
    ) -> Any:
        self.calls.append((rows, week_number, week_start))
        return self.response


class _Voice:
    def __init__(
        self, response: object = "voiced weekly plan", error: Exception | None = None
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple[object, object]] = []

    def compose(self, request: object, *, fallback_message: object) -> Any:
        self.calls.append((request, fallback_message))
        if self.error is not None:
            raise self.error
        return self.response


class _Dal:
    def __init__(
        self,
        *,
        active_plan: object = None,
        rows: object = None,
        active_error: Exception | None = None,
        week_error: Exception | None = None,
    ) -> None:
        self.active_plan = (
            {"id": 42, "start_date": date(2024, 9, 2), "weeks": 4}
            if active_plan is None
            else active_plan
        )
        self.rows = (
            [{"day_of_week": 1, "exercise_name": "Squat"}] if rows is None else rows
        )
        self.active_error = active_error
        self.week_error = week_error
        self.calls: list[tuple[str, object, int]] = []

    def get_active_plan(self) -> Any:
        if self.active_error is not None:
            raise self.active_error
        return self.active_plan

    def get_plan_week_rows(self, plan_id: object, week_number: int) -> Any:
        self.calls.append(("rows", plan_id, week_number))
        if self.week_error is not None:
            raise self.week_error
        return self.rows


def _orchestrator(
    dal: object | None,
    *,
    renderer: object = None,
    voice: object = None,
) -> SimpleNamespace:
    values: dict[str, object] = {"dal": dal}
    if renderer is not _MISSING:
        values["narrative_builder"] = renderer
    if voice is not _MISSING:
        values["voice_service"] = voice
    return SimpleNamespace(**values)


_MISSING = object()


@pytest.mark.parametrize(
    "dal",
    [
        None,
        SimpleNamespace(),
        SimpleNamespace(get_active_plan=lambda: {}),
        SimpleNamespace(get_plan_week_rows=lambda _plan_id, _week: []),
        SimpleNamespace(
            get_active_plan=None, get_plan_week_rows=lambda _plan_id, _week: []
        ),
        SimpleNamespace(get_active_plan=lambda: {}, get_plan_week_rows=None),
    ],
)
def test_missing_reader_capability_is_exact(dal: object | None) -> None:
    assert messenger.build_weekly_plan_overview(orchestrator=_orchestrator(dal)) == (
        "Training plan data source is not available."
    )


def test_get_plan_week_is_preferred_over_rows_and_receives_raw_identifier() -> None:
    class BothReaders(_Dal):
        def get_plan_week(
            self, plan_id: object, week_number: int
        ) -> list[dict[str, object]]:
            self.calls.append(("preferred", plan_id, week_number))
            return [{"day_of_week": 1, "exercise_name": "Preferred"}]

    dal = BothReaders(active_plan={"id": "raw-id", "start_date": TARGET, "weeks": 1})
    renderer = _Renderer()

    assert (
        messenger.build_weekly_plan_overview(
            orchestrator=_orchestrator(dal, renderer=renderer), target_date=TARGET
        )
        == "rendered weekly plan"
    )
    assert dal.calls == [("preferred", "raw-id", 1)]


def test_active_plan_exception_message_and_log_are_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logs: list[tuple[str, str]] = []
    monkeypatch.setattr(
        messenger.log_utils,
        "log_message",
        lambda message, level: logs.append((message, level)),
    )

    result = messenger.build_weekly_plan_overview(
        orchestrator=_orchestrator(_Dal(active_error=RuntimeError("offline"))),
        target_date=TARGET,
    )

    assert result == "Failed to load the active training plan."
    assert logs == [("Failed to load active plan: offline", "ERROR")]


@pytest.mark.parametrize("active_plan", [None, {}, False, 0, ""])
def test_falsey_active_plan_variants_are_no_plan(active_plan: object) -> None:
    dal = _Dal()
    dal.active_plan = active_plan
    assert (
        messenger.build_weekly_plan_overview(
            orchestrator=_orchestrator(dal), target_date=TARGET
        )
        == "There is no active training plan in the database."
    )


def test_truthy_non_mapping_active_plan_error_is_preserved() -> None:
    dal = _Dal(active_plan="truthy-not-a-plan")
    with pytest.raises(AttributeError, match="has no attribute 'get'"):
        messenger.build_weekly_plan_overview(
            orchestrator=_orchestrator(dal), target_date=TARGET
        )


@pytest.mark.parametrize(
    ("start_value", "expected_week", "expected_start"),
    [
        (datetime(2024, 9, 2, 23, 59), 2, date(2024, 9, 9)),
        (date(2024, 9, 2), 2, date(2024, 9, 9)),
        ("2024-09-02", 2, date(2024, 9, 9)),
    ],
)
def test_start_date_coercion_and_week_boundary_are_exact(
    start_value: object, expected_week: int, expected_start: date
) -> None:
    dal = _Dal(active_plan={"id": 42, "start_date": start_value, "weeks": "2"})
    renderer = _Renderer()
    messenger.build_weekly_plan_overview(
        orchestrator=_orchestrator(dal, renderer=renderer), target_date=TARGET
    )
    assert dal.calls == [("rows", 42, expected_week)]
    assert renderer.calls[0][1:] == (expected_week, expected_start)


def test_invalid_string_start_date_logs_but_other_invalid_types_do_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logs: list[tuple[str, str]] = []
    monkeypatch.setattr(
        messenger.log_utils,
        "log_message",
        lambda message, level: logs.append((message, level)),
    )

    invalid_string = _Dal(
        active_plan={"id": 42, "start_date": "not-a-date", "weeks": 4}
    )
    assert (
        messenger.build_weekly_plan_overview(
            orchestrator=_orchestrator(invalid_string), target_date=TARGET
        )
        == "The active training plan has an invalid start date."
    )
    assert logs == [("Active plan start date could not be parsed.", "ERROR")]

    logs.clear()
    invalid_type = _Dal(active_plan={"id": 42, "start_date": 123, "weeks": 4})
    assert (
        messenger.build_weekly_plan_overview(
            orchestrator=_orchestrator(invalid_type), target_date=TARGET
        )
        == "The active training plan has an invalid start date."
    )
    assert logs == []


def test_target_before_start_is_exact_and_does_not_load_week() -> None:
    dal = _Dal(active_plan={"id": 42, "start_date": date(2024, 9, 10), "weeks": 4})
    assert (
        messenger.build_weekly_plan_overview(
            orchestrator=_orchestrator(dal), target_date=TARGET
        )
        == "The active training plan starts on 2024-09-10."
    )
    assert dal.calls == []


@pytest.mark.parametrize("weeks", [None, 0, -1, "bad", object(), False])
def test_missing_or_invalid_duration_is_exact(weeks: object) -> None:
    dal = _Dal(active_plan={"id": 42, "start_date": TARGET, "weeks": weeks})
    assert (
        messenger.build_weekly_plan_overview(
            orchestrator=_orchestrator(dal), target_date=TARGET
        )
        == "The active training plan is missing its duration."
    )


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        (date(2024, 9, 2), "rendered weekly plan"),
        (date(2024, 9, 8), "rendered weekly plan"),
        (date(2024, 9, 22), "rendered weekly plan"),
        (
            date(2024, 9, 23),
            "The current training plan has finished. Time to generate a new one!",
        ),
    ],
)
def test_current_last_and_finished_week_edges(target: date, expected: str) -> None:
    dal = _Dal(active_plan={"id": 42, "start_date": date(2024, 9, 2), "weeks": 3})
    assert (
        messenger.build_weekly_plan_overview(
            orchestrator=_orchestrator(dal, renderer=_Renderer()), target_date=target
        )
        == expected
    )


def test_sunday_default_targets_monday_but_explicit_sunday_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Sunday(date):
        @classmethod
        def today(cls) -> Sunday:
            return cls(2024, 9, 8)

    monkeypatch.setattr(messenger, "date", Sunday)
    dal = _Dal(active_plan={"id": 42, "start_date": Sunday(2024, 9, 2), "weeks": 2})
    renderer = _Renderer()
    orch = _orchestrator(dal, renderer=renderer)

    messenger.build_weekly_plan_overview(orchestrator=orch)
    messenger.build_weekly_plan_overview(orchestrator=orch, target_date=Sunday.today())

    assert dal.calls == [("rows", 42, 2), ("rows", 42, 1)]


def test_missing_identifier_only_rejects_none() -> None:
    missing = _Dal(active_plan={"id": None, "start_date": TARGET, "weeks": 1})
    assert (
        messenger.build_weekly_plan_overview(
            orchestrator=_orchestrator(missing), target_date=TARGET
        )
        == "The active training plan is missing its identifier."
    )

    for identifier in (0, ""):
        dal = _Dal(active_plan={"id": identifier, "start_date": TARGET, "weeks": True})
        assert (
            messenger.build_weekly_plan_overview(
                orchestrator=_orchestrator(dal, renderer=_Renderer()),
                target_date=TARGET,
            )
            == "rendered weekly plan"
        )
        assert dal.calls == [("rows", identifier, 1)]


def test_week_loader_exception_message_arguments_and_log_are_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logs: list[tuple[str, str]] = []
    monkeypatch.setattr(
        messenger.log_utils,
        "log_message",
        lambda message, level: logs.append((message, level)),
    )
    dal = _Dal(week_error=RuntimeError("broken rows"))

    assert (
        messenger.build_weekly_plan_overview(
            orchestrator=_orchestrator(dal), target_date=date(2024, 9, 2)
        )
        == "Could not retrieve workouts for Plan ID 42, Week 1."
    )
    assert dal.calls == [("rows", 42, 1)]
    assert logs == [("Failed to load plan week data: broken rows", "ERROR")]


@pytest.mark.parametrize("rows", [None, [], ()])
def test_falsey_week_row_containers_use_exact_missing_message(rows: object) -> None:
    dal = _Dal()
    dal.rows = rows
    assert (
        messenger.build_weekly_plan_overview(
            orchestrator=_orchestrator(dal), target_date=date(2024, 9, 2)
        )
        == "Could not find workout data for Plan ID 42, Week 1."
    )


def test_generator_rows_are_truthy_rendered_then_exhausted_for_voice_context() -> None:
    rows = (
        {"day_of_week": day, "exercise_name": name}
        for day, name in [(2, "Second"), (1, "First")]
    )

    class ConsumingRenderer(_Renderer):
        def build_weekly_plan(
            self, rows: object, week_number: int, week_start: date | None = None
        ) -> str:
            self.calls.append((list(rows), week_number, week_start))  # type: ignore[arg-type]
            return "rendered generator"

    dal = _Dal(rows=rows)
    renderer = ConsumingRenderer()
    voice = _Voice()
    result = messenger.build_weekly_plan_overview(
        orchestrator=_orchestrator(dal, renderer=renderer, voice=voice),
        target_date=date(2024, 9, 2),
    )

    assert result == "voiced weekly plan"
    assert [row["exercise_name"] for row in renderer.calls[0][0]] == ["Second", "First"]
    request = voice.calls[0][0]
    assert request.recent_context["plan_week_rows"] == []
    assert request.must_include_facts[0].required_terms == ("1",)


@pytest.mark.parametrize(
    ("renderer", "error_type"),
    [
        (SimpleNamespace(), AttributeError),
        (SimpleNamespace(build_weekly_plan=None), TypeError),
    ],
)
def test_missing_or_non_callable_renderer_method_errors_are_preserved(
    renderer: object, error_type: type[Exception]
) -> None:
    with pytest.raises(error_type):
        messenger.build_weekly_plan_overview(
            orchestrator=_orchestrator(_Dal(), renderer=renderer),
            target_date=date(2024, 9, 2),
        )


def test_renderer_exception_and_malformed_row_error_propagate() -> None:
    class RaisingRenderer(_Renderer):
        def build_weekly_plan(
            self, rows: object, week_number: int, week_start: date | None = None
        ) -> str:
            raise RuntimeError("render failed")

    with pytest.raises(RuntimeError, match="render failed"):
        messenger.build_weekly_plan_overview(
            orchestrator=_orchestrator(_Dal(), renderer=RaisingRenderer()),
            target_date=date(2024, 9, 2),
        )

    with pytest.raises(AttributeError, match="has no attribute 'get'"):
        messenger.build_weekly_plan_overview(
            orchestrator=_orchestrator(_Dal(rows=["bad row"]), renderer=None),
            target_date=date(2024, 9, 2),
        )


@pytest.mark.parametrize(
    "voice", [_MISSING, None, SimpleNamespace(), SimpleNamespace(compose=None)]
)
def test_absent_or_non_callable_voice_composer_returns_fallback(voice: object) -> None:
    assert (
        messenger.build_weekly_plan_overview(
            orchestrator=_orchestrator(_Dal(), renderer=_Renderer(), voice=voice),
            target_date=date(2024, 9, 2),
        )
        == "rendered weekly plan"
    )


def test_composer_exception_and_invalid_return_are_not_changed() -> None:
    with pytest.raises(RuntimeError, match="voice failed"):
        messenger.build_weekly_plan_overview(
            orchestrator=_orchestrator(
                _Dal(),
                renderer=_Renderer(),
                voice=_Voice(error=RuntimeError("voice failed")),
            ),
            target_date=date(2024, 9, 2),
        )

    result = messenger.build_weekly_plan_overview(
        orchestrator=_orchestrator(
            _Dal(), renderer=_Renderer(), voice=_Voice(response=None)
        ),
        target_date=date(2024, 9, 2),
    )
    assert result is None


def test_voice_request_fields_profile_context_and_required_terms_are_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    state = {
        "profile": {"display_name": "Pete Client", "timezone": "UTC"},
        "goal_state": {"race": "A race"},
        "plan_context": {"phase": "build"},
        "recent_workouts": {"running": ["tempo"]},
        "coaching_notes": ["Keep the schedule exact."],
    }

    class Metrics:
        def __init__(self, dal: object) -> None:
            seen["dal"] = dal

        def coach_state(self, iso_date: str, *, principal: object) -> object:
            seen["date"] = iso_date
            seen["principal"] = principal
            return state

    monkeypatch.setattr(api_services, "MetricsService", Metrics)
    rows = [
        {"day_of_week": 1, "exercise_name": " Squat "},
        {"day_of_week": 1, "exercise_name": "Squat"},
        {"day_of_week": 2, "exercise_name": ""},
        {"day_of_week": 2, "exercise_name": None},
        *(
            {"day_of_week": 3, "exercise_name": f"Exercise {number}"}
            for number in range(1, 12)
        ),
        SimpleNamespace(exercise_name="ignored"),
    ]
    dal = _Dal(
        active_plan={"id": 9, "start_date": date(2024, 9, 2), "weeks": 2}, rows=rows
    )
    voice = _Voice()

    assert (
        messenger.build_weekly_plan_overview(
            orchestrator=_orchestrator(
                dal, renderer=_Renderer("exact schedule"), voice=voice
            ),
            target_date=TARGET,
        )
        == "voiced weekly plan"
    )

    request = voice.calls[0][0]
    assert request.message_type == "weekly_plan"
    assert request.intent == "weekly training plan overview"
    assert request.audience == {"name": "Pete Client", "timezone": "UTC"}
    assert request.dates == {
        "target_date": "2024-09-09",
        "week_start": "2024-09-09",
        "week_end": "2024-09-15",
    }
    assert request.metrics_report == {}
    assert request.coach_state is state
    assert request.goals == {"race": "A race"}
    assert request.recent_context == {
        "active_plan": dal.active_plan,
        "plan_week_rows": rows,
        "plan_context": {"phase": "build"},
        "recent_workouts": {"running": ["tempo"]},
    }
    assert request.deterministic_decisions == {
        "week_number": 2,
        "week_start": "2024-09-09",
        "exact_schedule_must_be_preserved": True,
    }
    assert request.constraints_and_warnings == ["Keep the schedule exact."]
    assert request.must_include_facts[0].as_dict() == {
        "id": "weekly_plan_schedule",
        "text": "exact schedule",
        "required": True,
        "source": "training_plan",
        "required_terms": [
            "2",
            "Squat",
            "Exercise 1",
            "Exercise 2",
            "Exercise 3",
            "Exercise 4",
            "Exercise 5",
            "Exercise 6",
            "Exercise 7",
            "Exercise 8",
            "Exercise 9",
        ],
    }
    assert request.style == {
        "channel": "telegram",
        "voice": "Pete",
        "tone": "clear, personal, trainer-like, practical",
        "max_words": 260,
        "format": "compact weekly schedule with exact sessions preserved",
    }
    principal = seen["principal"]
    assert principal.machine_client_id == "local-cli"
    assert principal.auth_scheme == "cli"
    assert seen["date"] == "2024-09-09"
    assert seen["dal"] is dal


def test_coach_state_failure_and_non_dict_state_quirk_are_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logs: list[tuple[str, str]] = []
    monkeypatch.setattr(
        messenger.log_utils,
        "log_message",
        lambda message, level: logs.append((message, level)),
    )

    class FailingMetrics:
        def __init__(self, _dal: object) -> None:
            pass

        def coach_state(self, _iso_date: str, *, principal: object) -> object:
            raise RuntimeError("context offline")

    monkeypatch.setattr(api_services, "MetricsService", FailingMetrics)
    voice = _Voice()
    messenger.build_weekly_plan_overview(
        orchestrator=_orchestrator(_Dal(), renderer=_Renderer(), voice=voice),
        target_date=date(2024, 9, 2),
    )
    assert logs == [
        (
            "Failed to load structured coach state for weekly voice context: context offline",
            "WARN",
        )
    ]
    assert voice.calls[0][0].coach_state == {}

    class NonDictMetrics(FailingMetrics):
        def coach_state(self, _iso_date: str, *, principal: object) -> object:
            return ["legacy", "state"]

    monkeypatch.setattr(api_services, "MetricsService", NonDictMetrics)
    voice = _Voice()
    messenger.build_weekly_plan_overview(
        orchestrator=_orchestrator(_Dal(), renderer=_Renderer(), voice=voice),
        target_date=date(2024, 9, 2),
    )
    request = voice.calls[0][0]
    assert request.coach_state == ["legacy", "state"]
    assert request.audience == {"name": "Ric", "timezone": "Europe/London"}
    assert request.goals == {}
    assert request.constraints_and_warnings == []


runner = CliRunner()


class _CliOrchestrator:
    def __init__(self, *, send_result: bool = True) -> None:
        self.send_result = send_result
        self.sent: list[str] = []

    def send_telegram_message(self, message: str) -> bool:
        self.sent.append(message)
        return self.send_result


@pytest.mark.contract
def test_real_typer_plan_empty_send_guard_and_no_send_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orch = _CliOrchestrator()
    logs: list[tuple[str, str]] = []
    monkeypatch.setattr(messenger, "_build_orchestrator", lambda: orch)
    monkeypatch.setattr(messenger, "build_weekly_plan_overview", lambda **_kwargs: "")
    monkeypatch.setattr(
        messenger.log_utils,
        "log_message",
        lambda message, level: logs.append((message, level)),
    )

    no_send = runner.invoke(messenger.app, ["message", "--plan"])
    with_send = runner.invoke(messenger.app, ["message", "--plan", "--send"])

    assert no_send.exit_code == 0
    assert no_send.stdout == "--- Weekly Plan ---\n\n"
    assert with_send.exit_code == 1
    assert orch.sent == []
    assert logs == [
        ("Generating weekly plan overview...", "INFO"),
        ("Generating weekly plan overview...", "INFO"),
        ("Weekly plan overview was empty; aborting Telegram send.", "WARN"),
    ]


@pytest.mark.contract
def test_real_typer_plan_selector_absence_and_voice_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orch = _CliOrchestrator()
    monkeypatch.setattr(messenger, "_build_orchestrator", lambda: orch)
    monkeypatch.setattr(orch, "dal", SimpleNamespace(), raising=False)

    absent = runner.invoke(messenger.app, ["message", "--plan"])
    assert absent.exit_code == 0
    assert absent.stdout == (
        "--- Weekly Plan ---\nTraining plan data source is not available.\n"
    )

    monkeypatch.setattr(
        messenger,
        "build_weekly_plan_overview",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("voice failed")),
    )
    failed = runner.invoke(messenger.app, ["message", "--plan"])
    assert failed.exit_code == 1
    assert isinstance(failed.exception, RuntimeError)
    assert str(failed.exception) == "voice failed"


@pytest.mark.contract
def test_real_typer_multiple_message_flags_remain_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orch = _CliOrchestrator()
    monkeypatch.setattr(messenger, "_build_orchestrator", lambda: orch)
    monkeypatch.setattr(messenger, "build_daily_summary", lambda **_kwargs: "daily")
    monkeypatch.setattr(messenger, "build_trainer_summary", lambda **_kwargs: "trainer")
    monkeypatch.setattr(
        messenger, "build_weekly_plan_overview", lambda **_kwargs: "weekly"
    )

    result = runner.invoke(
        messenger.app,
        ["message", "--summary", "--trainer", "--plan"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.stdout == (
        "--- Daily Summary ---\ndaily\n"
        "--- Trainer Summary ---\ntrainer\n"
        "--- Weekly Plan ---\nweekly\n"
    )
    assert orch.sent == []
