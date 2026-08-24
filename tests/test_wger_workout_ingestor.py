from __future__ import annotations

from datetime import date
from decimal import Decimal

from pete_e.infrastructure.wger_workout_ingestor import WgerWorkoutLogIngestor


class _Repository:
    def __init__(self) -> None:
        self.validated: list[list[int]] = []
        self.reconciled: list[tuple[date, date, list]] = []

    def validate_wger_exercise_ids(self, exercise_ids):
        self.validated.append(list(exercise_ids))

    def reconcile_wger_logs(self, *, start_date, end_date, workout_sets):
        values = list(workout_sets)
        self.reconciled.append((start_date, end_date, values))
        return len(values)


class _Client:
    def __init__(self, logs, units=(), repetition_units=()) -> None:
        self.logs = list(logs)
        self.units = list(units)
        self.repetition_units = list(repetition_units)
        self.requests: list[tuple[date, date]] = []
        self.unit_requests = 0
        self.repetition_unit_requests = 0

    def get_workout_logs(self, start_date, end_date):
        self.requests.append((start_date, end_date))
        return list(self.logs)

    def get_weight_units(self):
        self.unit_requests += 1
        return list(self.units)

    def get_repetition_units(self):
        self.repetition_unit_requests += 1
        return list(self.repetition_units)


def test_ingestor_normalizes_units_timezone_and_deterministic_set_numbers() -> None:
    repository = _Repository()
    client = _Client(
        [
            {
                "id": "b-set",
                "date": "2026-08-17T09:00:00+01:00",
                "session": "session-2",
                "exercise": 615,
                "repetitions": "5.00",
                "weight": "60.00",
                "weight_unit": "kg",
                "rir": "2.0",
            },
            {
                "id": "a-set",
                "date": "2026-08-16T23:30:00Z",
                "session": "session-1",
                "exercise": 615,
                "repetitions": "8",
                "weight": "100",
                "weight_unit": 6,
                "rir": None,
            },
            {
                "id": "timed-set",
                "date": "2026-08-18T12:00:00Z",
                "exercise": 999,
                "repetitions": "30.5",
                "repetitions_unit": 9,
                "weight": None,
            },
        ],
        units=[{"id": 6, "name": "lb"}],
        repetition_units=[{"id": 9, "name": "seconds", "unit_type": "TIME"}],
    )
    ingestor = WgerWorkoutLogIngestor(
        repository=repository,
        client=client,
        timezone_name="Europe/London",
    )

    result = ingestor.ingest(
        start_date=date(2026, 8, 17),
        end_date=date(2026, 8, 23),
    )

    assert result.success is True
    assert result.summary is not None
    assert result.summary.fetched == 3
    assert result.summary.accepted == 2
    assert result.summary.skipped == 1
    assert result.summary.stored == 2
    assert client.unit_requests == 1
    assert client.repetition_unit_requests == 1
    _, _, stored = repository.reconciled[0]
    assert [item.source_id for item in stored] == ["a-set", "b-set"]
    assert [item.day for item in stored] == [date(2026, 8, 17), date(2026, 8, 17)]
    assert [item.set_number for item in stored] == [1, 2]
    assert stored[0].weight_kg == Decimal("45.359")
    assert stored[1].weight_kg == Decimal("60.000")


def test_ingestor_dry_run_validates_without_reconciling() -> None:
    repository = _Repository()
    client = _Client(
        [
            {
                "id": "set-1",
                "date": "2026-08-20",
                "exercise": 73,
                "repetitions": "3",
                "weight": "0",
            }
        ]
    )
    ingestor = WgerWorkoutLogIngestor(repository=repository, client=client)

    result = ingestor.ingest(
        start_date=date(2026, 8, 17),
        end_date=date(2026, 8, 23),
        dry_run=True,
    )

    assert result.success is True
    assert result.statuses == {"Wger": "dry-run"}
    assert result.summary is not None
    assert result.summary.stored == 0
    assert repository.validated == [[73]]
    assert repository.reconciled == []


def test_ingestor_rejects_the_entire_window_before_persistence() -> None:
    repository = _Repository()
    client = _Client(
        [
            {
                "id": "bad-unit",
                "date": "2026-08-20T10:00:00Z",
                "exercise": 615,
                "repetitions": "5",
                "weight": "100",
                "weight_unit": "stone",
            }
        ]
    )
    ingestor = WgerWorkoutLogIngestor(repository=repository, client=client)

    result = ingestor.ingest(
        start_date=date(2026, 8, 17),
        end_date=date(2026, 8, 23),
    )

    assert result.success is False
    assert result.statuses == {"Wger": "failed"}
    assert "unknown weight unit" in (result.error or "")
    assert repository.reconciled == []
