from __future__ import annotations

from datetime import date

from pete_e.application.plan_read_model import PlanReadModel


class StubDal:
    def get_plan_for_day(self, target_date: date):
        return ["exercise_name", "sets"], [["Squat", 5], {"exercise_name": "Run", "sets": None}]

    def get_plan_for_week(self, start_date: date):
        return ["day", "exercise_name"], [["Mon", "Bench"]]

    def get_plan_decision_trace(self, plan_id: int, week_number: int):
        assert plan_id == 9
        assert week_number == 2
        return [{"week_number": 2, "stage": "constraint_heavy_strength_run_quality", "reason_code": "constraint_applied"}]


def test_plan_for_day_normalizes_rows_to_records() -> None:
    payload = PlanReadModel(StubDal()).plan_for_day(date(2024, 2, 2))

    assert payload["columns"] == ["exercise_name", "sets"]
    assert payload["rows"] == [
        {"exercise_name": "Squat", "sets": 5},
        {"exercise_name": "Run", "sets": None},
    ]


def test_plan_for_week_normalizes_sequence_rows() -> None:
    payload = PlanReadModel(StubDal()).plan_for_week(date(2024, 2, 5))

    assert payload["rows"] == [{"day": "Mon", "exercise_name": "Bench"}]


def test_load_day_context_returns_normalized_rows() -> None:
    rows = PlanReadModel(StubDal()).load_day_context(date(2024, 2, 2))

    assert rows[0]["exercise_name"] == "Squat"


def test_decision_trace_for_week_reads_persisted_trace() -> None:
    payload = PlanReadModel(StubDal()).decision_trace_for_week(plan_id=9, week_number=2)
    assert payload["plan_id"] == 9
    assert payload["week_number"] == 2
    assert payload["trace"][0]["stage"] == "constraint_heavy_strength_run_quality"
