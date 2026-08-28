"""Pre-extraction contracts for both daily-summary enrichment paths."""

from __future__ import annotations

from datetime import date, timedelta
from types import MethodType, SimpleNamespace
import pytest

from pete_e.application import orchestrator as orchestrator_module
from pete_e.application.orchestrator import Orchestrator
from pete_e.cli import messenger


TARGET = date(2026, 8, 23)
STEPS_LINE = (
    "Steps trend: 10,000 steps/day "
    "(steady vs 30d avg 10,000 steps/day; 60d base 10,000 steps/day)."
)
SLEEP_LINE = (
    "Sleep trend: 7.0 h/night " "(steady vs 30d avg 7.0 h/night; 60d base 7.0 h/night)."
)


class _SnapshotDal:
    def __init__(self) -> None:
        self.history = [
            {
                "date": TARGET - timedelta(days=offset),
                "steps": 10_000,
                "sleep_asleep_minutes": 420,
                "body_age_years": (
                    38.6 if offset == 0 else (39.2 if offset == 7 else None)
                ),
            }
            for offset in range(90)
        ]
        self.metrics = [
            {
                "date": TARGET - timedelta(days=offset),
                "muscle_pct": 42.0 if offset < 7 else 39.5,
                "hrv_sdnn_ms": 75.0 if offset == 0 else 70.0,
            }
            for offset in range(14)
        ]

    def get_metrics_overview(self, target: date):
        return ["metric_name", "yesterday_value"], [("weight", 82.0)]

    def get_historical_data(self, start: date, end: date):
        return [row for row in self.history if start <= row["date"] <= end]

    def get_historical_metrics(self, days: int):
        return list(reversed(self.metrics[:days]))

    def get_nutrition_daily_summary(self, target: date):
        return {"meals_logged": 0}


class _Narrative:
    def build_daily_narrative(self, payload: dict[str, object]) -> str:
        return "Base summary"


class _LegacyOrchestrator:
    def __init__(self, dal: object, summary: object = "Base summary") -> None:
        self.dal = dal
        self.summary = summary
        self.requested: list[date | None] = []

    def get_daily_summary(self, target_date: date | None = None) -> object:
        self.requested.append(target_date)
        return self.summary


def _production_orchestrator(dal: object) -> Orchestrator:
    orchestrator = object.__new__(Orchestrator)
    orchestrator.dal = dal
    orchestrator.narrative_builder = _Narrative()
    orchestrator._build_morning_training_guidance = MethodType(
        lambda self, **kwargs: None,
        orchestrator,
    )
    orchestrator._build_nutrition_summary_line = MethodType(
        lambda self, target: None,
        orchestrator,
    )
    return orchestrator


def test_identical_dataset_pins_production_and_legacy_render_profiles() -> None:
    dal = _SnapshotDal()

    production = _production_orchestrator(dal).get_daily_summary(target_date=TARGET)
    legacy = messenger.build_daily_summary(
        orchestrator=_LegacyOrchestrator(dal),
        target_date=TARGET,
    )

    shared_prefix = (
        "Base summary\n"
        "Body Age: 38.6y (7d delta -0.6y)\n"
        "Muscle trend: 42.0% avg this week (up 2.5% vs prior).\n"
    )
    shared_suffix = f"\nTrend check: {STEPS_LINE} {SLEEP_LINE}"
    assert production == (
        shared_prefix + "HRV: 75 ms (up) vs 7d avg 70 ms" + shared_suffix
    )
    assert legacy == shared_prefix + "HRV: 75 ms ↗ (7d avg 70 ms)" + shared_suffix


@pytest.mark.parametrize(
    ("value", "expected"),
    [("text", "text"), (None, ""), (17, "17")],
)
def test_callable_authoritative_builder_is_used_and_coerced(
    value: object,
    expected: str,
) -> None:
    calls: list[date | None] = []

    class _Authoritative:
        def build_daily_summary_message(
            self, target_date: date | None = None
        ) -> object:
            calls.append(target_date)
            return value

        def get_daily_summary(self, target_date: date | None = None) -> str:
            raise AssertionError("fallback must not run")

    assert (
        messenger.build_daily_summary(
            orchestrator=_Authoritative(),
            target_date=TARGET,
        )
        == expected
    )
    assert calls == [TARGET]


@pytest.mark.parametrize(("value", "expected"), [(None, ""), (19, "19")])
def test_non_callable_builder_uses_duck_typed_fallback(
    value: object,
    expected: str,
) -> None:
    orchestrator = _LegacyOrchestrator(dal=None, summary=value)
    orchestrator.build_daily_summary_message = None

    assert (
        messenger.build_daily_summary(
            orchestrator=orchestrator,
            target_date=TARGET,
        )
        == expected
    )
    assert orchestrator.requested == [TARGET]


def test_default_yesterday_and_explicit_target_are_forwarded_in_legacy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FixedDate(date):
        @classmethod
        def today(cls) -> date:
            return date(2026, 8, 24)

    monkeypatch.setattr(messenger, "date", _FixedDate)
    orchestrator = _LegacyOrchestrator(dal=None)

    messenger.build_daily_summary(orchestrator=orchestrator)
    messenger.build_daily_summary(orchestrator=orchestrator, target_date=TARGET)

    assert orchestrator.requested == [None, TARGET]


def test_default_yesterday_and_explicit_target_are_loaded_in_production_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[date] = []

    class _FixedDate(date):
        @classmethod
        def today(cls) -> date:
            return cls(2026, 8, 24)

    class _Dal:
        def get_metrics_overview(self, target: date):
            requested.append(target)
            return [], []

        def get_nutrition_daily_summary(self, target: date):
            return {}

    monkeypatch.setattr(orchestrator_module, "date", _FixedDate)
    orchestrator = _production_orchestrator(_Dal())

    orchestrator.get_daily_summary()
    orchestrator.get_daily_summary(target_date=TARGET)

    assert requested == [date(2026, 8, 23), TARGET]


def test_body_age_absence_keeps_intentional_profile_divergence() -> None:
    trend = SimpleNamespace(value=None, delta=None)
    legacy = messenger._format_body_age_line(trend)

    class _Dal:
        pass

    production = _production_orchestrator(_Dal())._format_body_age_line(TARGET)

    assert legacy == "Body Age: n/a"
    assert production is None


@pytest.mark.parametrize(
    ("trend", "expected"),
    [
        (None, None),
        (SimpleNamespace(value=38.6, delta=None), "Body Age: 38.6y (7d delta n/a)"),
        (
            SimpleNamespace(value=38.6, delta=-0.6),
            "Body Age: 38.6y (7d delta -0.6y)",
        ),
    ],
)
def test_legacy_body_age_states_are_exact(trend: object, expected: str | None) -> None:
    assert messenger._format_body_age_line(trend) == expected


class _MetricDal:
    def __init__(self, rows: object) -> None:
        self.rows = rows
        self.requests: list[int] = []

    def get_historical_metrics(self, days: int) -> object:
        self.requests.append(days)
        return self.rows


def _muscle_rows(current: float, previous: float, *, current_count: int = 3):
    rows = [
        {"date": TARGET - timedelta(days=offset), "muscle_pct": current}
        for offset in range(current_count)
    ]
    rows.extend(
        {"date": TARGET - timedelta(days=7 + offset), "muscle_pct": previous}
        for offset in range(3)
    )
    return rows


@pytest.mark.parametrize(
    ("current", "previous", "expected_fragment"),
    [
        (40.5, 40.0, "up 0.5% vs prior"),
        (39.5, 40.0, "down 0.5% vs prior"),
        (40.44, 40.0, "steady vs prior"),
    ],
)
def test_body_composition_thresholds_and_rounding_are_exact(
    current: float,
    previous: float,
    expected_fragment: str,
) -> None:
    dal = _MetricDal(_muscle_rows(current, previous))

    assert expected_fragment in messenger._format_body_comp_line(dal, TARGET)
    assert expected_fragment in _production_orchestrator(dal)._format_body_comp_line(
        TARGET
    )
    assert dal.requests == [14, 14]


def test_body_composition_minimum_and_no_prior_window_are_preserved() -> None:
    too_sparse = _MetricDal(_muscle_rows(42.0, 39.5, current_count=2))
    no_prior = _MetricDal(
        [
            {"date": TARGET - timedelta(days=offset), "muscle_pct": 42.04}
            for offset in range(3)
        ]
    )

    assert messenger._format_body_comp_line(too_sparse, TARGET) is None
    assert (
        messenger._format_body_comp_line(no_prior, TARGET)
        == "Muscle trend: 42.0% avg this week."
    )


def test_body_composition_generator_and_malformed_rows_are_characterized() -> None:
    rows = [
        {"date": "not-a-date", "muscle_pct": 99},
        {"date": TARGET - timedelta(days=14), "muscle_pct": 99},
        {"date": TARGET - timedelta(days=2), "muscle_pct": "bad"},
        *_muscle_rows(42.0, 40.0),
    ]
    dal = _MetricDal((row for row in rows))

    assert (
        messenger._format_body_comp_line(dal, TARGET)
        == "Muscle trend: 42.0% avg this week (up 2.0% vs prior)."
    )


def test_body_composition_none_and_non_dict_rows_keep_profile_difference() -> None:
    with pytest.raises(TypeError):
        messenger._format_body_comp_line(_MetricDal(None), TARGET)
    with pytest.raises(AttributeError):
        messenger._format_body_comp_line(_MetricDal([None]), TARGET)

    assert (
        _production_orchestrator(_MetricDal(None))._format_body_comp_line(TARGET)
        is None
    )
    assert (
        _production_orchestrator(_MetricDal([None]))._format_body_comp_line(TARGET)
        is None
    )


def test_numeric_string_body_composition_keeps_profile_difference() -> None:
    rows = _muscle_rows("42.0", "40.0")

    assert "up 2.0%" in messenger._format_body_comp_line(_MetricDal(rows), TARGET)
    with pytest.raises(TypeError):
        _production_orchestrator(_MetricDal(rows))._format_body_comp_line(TARGET)


def _hrv_rows(current: object, previous: object = 70.0) -> list[dict[str, object]]:
    return [
        {"date": TARGET, "hrv_sdnn_ms": current},
        {"date": TARGET - timedelta(days=1), "hrv_sdnn_ms": previous},
    ]


@pytest.mark.parametrize(
    ("current", "legacy_arrow", "production_direction"),
    [(72.0, "↗", "up"), (71.99, "→", "steady"), (68.0, "↘", "down")],
)
def test_hrv_thresholds_keep_exact_render_profiles(
    current: float,
    legacy_arrow: str,
    production_direction: str,
) -> None:
    legacy = messenger._format_hrv_line(_MetricDal(_hrv_rows(current)), TARGET)
    production = _production_orchestrator(
        _MetricDal(_hrv_rows(current))
    )._format_hrv_line(TARGET)

    assert legacy == f"HRV: {current:.0f} ms {legacy_arrow} (7d avg 70 ms)"
    assert production == (
        f"HRV: {current:.0f} ms ({production_direction}) vs 7d avg 70 ms"
    )


def test_hrv_key_precedence_positive_filter_and_latest_selection() -> None:
    rows = [
        {"date": TARGET - timedelta(days=2), "hrv_sdnn_ms": 0, "hrv_rmssd_ms": 99},
        {"date": TARGET - timedelta(days=1), "hrv_rmssd_ms": 68},
        {"date": TARGET + timedelta(days=1), "hrv_sdnn_ms": 200},
    ]

    assert messenger._format_hrv_line(_MetricDal(rows), TARGET) == "HRV: 68 ms →"
    assert (
        _production_orchestrator(_MetricDal(rows))._format_hrv_line(TARGET)
        == "HRV: 68 ms (steady)"
    )


def test_hrv_first_valid_key_wins() -> None:
    rows = [
        {"date": TARGET, "hrv_sdnn_ms": 72, "hrv_rmssd_ms": 99},
        {"date": TARGET - timedelta(days=1), "hrv_sdnn_ms": 70},
    ]

    assert "HRV: 72 ms" in messenger._format_hrv_line(_MetricDal(rows), TARGET)
    assert "HRV: 72 ms" in _production_orchestrator(_MetricDal(rows))._format_hrv_line(
        TARGET
    )


def test_invalid_first_hrv_key_keeps_profile_difference() -> None:
    rows = [
        {"date": TARGET, "hrv_sdnn_ms": "bad", "hrv_rmssd_ms": 72},
        {"date": TARGET - timedelta(days=1), "hrv_sdnn_ms": 70},
    ]

    assert (
        messenger._format_hrv_line(_MetricDal(rows), TARGET)
        == "HRV: 72 ms ↗ (7d avg 70 ms)"
    )
    with pytest.raises(TypeError):
        _production_orchestrator(_MetricDal(rows))._format_hrv_line(TARGET)


def test_hrv_target_value_wins_over_later_sorted_sample() -> None:
    rows = [
        {"date": TARGET - timedelta(days=1), "hrv_sdnn_ms": 60},
        {"date": TARGET, "hrv_sdnn_ms": 80},
        {"date": TARGET - timedelta(days=2), "hrv_sdnn_ms": 70},
    ]

    assert messenger._format_hrv_line(_MetricDal(rows), TARGET) == (
        "HRV: 80 ms ↗ (7d avg 65 ms)"
    )


def test_summary_date_datetime_branch_is_observably_shadowed() -> None:
    from datetime import datetime

    value = datetime(2026, 8, 23, 12, 30)

    assert messenger._coerce_summary_date(value) is value
    assert Orchestrator._coerce_date(value) is value


def test_trend_loading_filters_and_orders_rows() -> None:
    class _Dal:
        def get_historical_data(self, start: date, end: date):
            return [
                {"date": TARGET + timedelta(days=1), "steps": 1},
                None,
                {"date": "bad", "steps": 2},
                {"date": TARGET, "steps": 3},
                {"date": TARGET - timedelta(days=2), "steps": 4},
            ]

    expected = [
        (TARGET - timedelta(days=2), {"date": TARGET - timedelta(days=2), "steps": 4}),
        (TARGET, {"date": TARGET, "steps": 3}),
    ]
    assert messenger._collect_trend_samples(_Dal(), TARGET) == expected
    assert _production_orchestrator(_Dal())._collect_trend_samples(TARGET) == expected


def test_history_loader_exceptions_keep_warning_wording_and_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Dal:
        def get_historical_metrics(self, days: int):
            raise RuntimeError("offline")

    legacy_logs: list[tuple[str, str]] = []
    production_logs: list[str] = []
    monkeypatch.setattr(
        messenger.log_utils,
        "log_message",
        lambda message, level: legacy_logs.append((message, level)),
    )
    monkeypatch.setattr(
        orchestrator_module.log_utils,
        "warn",
        lambda message: production_logs.append(message),
    )

    assert messenger._format_body_comp_line(_Dal(), TARGET) is None
    assert _production_orchestrator(_Dal())._format_body_comp_line(TARGET) is None

    assert legacy_logs == [("Failed to load body composition history: offline", "WARN")]
    assert production_logs == [
        "Failed to load body composition history for voice context: offline"
    ]


@pytest.mark.parametrize(
    ("base", "addition", "expected"),
    [
        (None, "line", "line"),
        ("", "line", "line"),
        ("base", "line", "base\nline"),
        ("base\n", "line", "base\nline"),
        ("base", "", "base"),
    ],
)
def test_append_line_contract(base: str | None, addition: str, expected: str) -> None:
    assert messenger._append_line(base, addition) == expected
    assert Orchestrator._append_line(base, addition) == expected


def test_send_daily_summary_converts_values_and_skips_whitespace() -> None:
    sent: list[str] = []
    orchestrator = SimpleNamespace(
        send_telegram_message=lambda message: sent.append(message) or True
    )

    assert (
        messenger.send_daily_summary(
            orchestrator=orchestrator,
            summary_text=27,  # type: ignore[arg-type]
        )
        == "27"
    )
    assert (
        messenger.send_daily_summary(
            orchestrator=orchestrator,
            summary_text="  \n",
        )
        == "  \n"
    )
    assert sent == ["27"]


def test_send_daily_summary_none_builder_value_does_not_send() -> None:
    orchestrator = SimpleNamespace(
        build_daily_summary_message=lambda target_date=None: None,
        send_telegram_message=lambda message: (_ for _ in ()).throw(
            AssertionError("must not send")
        ),
    )

    assert messenger.send_daily_summary(orchestrator=orchestrator) == ""


def test_send_daily_summary_false_result_has_exact_error() -> None:
    orchestrator = SimpleNamespace(send_telegram_message=lambda message: False)

    with pytest.raises(
        RuntimeError,
        match=r"^Telegram send for daily summary failed\.$",
    ):
        messenger.send_daily_summary(orchestrator=orchestrator, summary_text="report")


def test_send_daily_summary_propagates_transport_exception() -> None:
    def _raise(message: str) -> bool:
        raise OSError("network")

    with pytest.raises(OSError, match="network"):
        messenger.send_daily_summary(
            orchestrator=SimpleNamespace(send_telegram_message=_raise),
            summary_text="report",
        )
