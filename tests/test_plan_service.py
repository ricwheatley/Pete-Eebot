from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

import pytest

from pete_e.application.services import PlanService
from pete_e.domain.plan_factory import PlanFactory
from pete_e.domain import schedule_rules
from pete_e.domain.repositories import PlanRepository
from pete_e.domain.prescription_validation import PrescriptionValidationError


class StubPlanRepository(PlanRepository):
    def __init__(self) -> None:
        # map lift id -> assistance exercise ids
        self._assistance: Dict[int, List[int]] = {
            schedule_rules.SQUAT_ID: [201, 202],
            schedule_rules.BENCH_ID: [301, 302],
            schedule_rules.OHP_ID: [401, 402],
            schedule_rules.DEADLIFT_ID: [501, 502],
        }
        self._core = [900, 901]
        """Initialize this object."""

    def get_assistance_pool_for(self, main_lift_id: int) -> List[int]:
        return list(self._assistance.get(main_lift_id, []))
        """Perform get assistance pool for."""

    def get_core_pool_ids(self) -> List[int]:
        return list(self._core)
        """Perform get core pool ids."""

    def get_latest_training_maxes(self) -> Dict[str, float]:
        return _training_maxes()
        """Perform get latest training maxes."""

    def save_full_plan(self, plan_dict: Dict[str, Any]) -> int:  # pragma: no cover - unused for factory tests
        self.saved_plan = plan_dict  # type: ignore[attr-defined]
        return 1
        """Perform save full plan."""
    """Represent StubPlanRepository."""


def _training_maxes() -> Dict[str, float]:
    return {
        "squat": 180.0,
        "bench": 120.0,
        "deadlift": 220.0,
        "ohp": 70.0,
    }
    """Perform training maxes."""


def test_plan_factory_computes_expected_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = StubPlanRepository()
    factory = PlanFactory(plan_repository=repo)
    tm = _training_maxes()

    # Make random selection deterministic
    monkeypatch.setattr("random.sample", lambda population, k: population[:k])

    plan = factory.create_531_block_plan(start_date=date(2024, 1, 1), training_maxes=tm)

    assert plan["weeks"] == 4
    first_week = plan["plan_weeks"][0]
    assert first_week["week_number"] == 1

    squat_sets = [
        workout for workout in first_week["workouts"] if workout["exercise_id"] == schedule_rules.SQUAT_ID
    ]
    top_set = max(squat_sets, key=lambda w: w["percent_1rm"])
    percent = schedule_rules.main_set_summary(1)["percent_1rm"]
    expected_weight = round((tm["squat"] * percent / 100) / 2.5) * 2.5
    assert top_set["target_weight_kg"] == pytest.approx(expected_weight)

    assistance_ids = [
        workout["exercise_id"]
        for workout in first_week["workouts"]
        if workout["exercise_id"] in repo._assistance[schedule_rules.SQUAT_ID]
    ]
    assert assistance_ids  # assistance movements should be present
    """Perform test plan factory computes expected targets."""


def test_plan_factory_records_programmed_difficulty(monkeypatch: pytest.MonkeyPatch) -> None:
    class MetadataRepo(StubPlanRepository):
        def get_exercise_difficulty_cap(self, *, as_of_date=None) -> Dict[str, Any]:
            return {
                "current_cap": 2,
                "source": "test",
                "evidence": {"available": True},
            }

        def get_assistance_candidates_for(
            self,
            main_lift_id: int,
            *,
            max_difficulty: int,
        ) -> List[Dict[str, int]]:
            return [
                {"exercise_id": self._assistance[main_lift_id][0], "difficulty": 1},
                {"exercise_id": self._assistance[main_lift_id][1], "difficulty": 2},
            ]

        def get_core_candidates(self, *, max_difficulty: int) -> List[Dict[str, int]]:
            return [{"exercise_id": self._core[0], "difficulty": 1}]

    repo = MetadataRepo()
    factory = PlanFactory(plan_repository=repo)
    monkeypatch.setattr("random.sample", lambda population, k: population[:k])

    plan = factory.create_531_block_plan(
        start_date=date(2024, 1, 1),
        training_maxes=_training_maxes(),
    )

    first_week = plan["plan_weeks"][0]
    assistance = [
        item
        for item in first_week["workouts"]
        if item["exercise_id"] in repo._assistance[schedule_rules.SQUAT_ID]
    ]
    assert {item["programmed_difficulty"] for item in assistance} == {1, 2}
    assert plan["metadata"]["exercise_difficulty"]["current_cap"] == 2
    assert (
        plan["metadata"]["exercise_difficulty"]["selection"]["core_candidate_count"]
        == 1
    )
    """Perform test plan factory records programmed difficulty."""


def test_plan_service_persists_full_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    saved_payload: Dict[str, Any] = {}

    class StubDal(StubPlanRepository):
        def get_latest_training_maxes(self) -> Dict[str, float]:
            return _training_maxes()
            """Perform get latest training maxes."""

        def save_full_plan(self, plan_dict: Dict[str, Any]) -> int:
            saved_payload.update(plan_dict)
            return 42
            """Perform save full plan."""
        """Represent StubDal."""

    service = PlanService(dal=StubDal())
    plan_id = service.create_and_persist_531_block(start_date=date(2024, 1, 1))

    assert plan_id == 42
    assert saved_payload["start_date"] == date(2024, 1, 1)
    assert saved_payload["weeks"] == 4
    assert len(saved_payload["plan_weeks"]) == 4
    """Perform test plan service persists full plan."""


def test_plan_service_refuses_to_persist_when_a_training_max_is_missing() -> None:
    class StubDal(StubPlanRepository):
        def __init__(self) -> None:
            super().__init__()
            self.saved = False

        def get_latest_training_maxes(self) -> Dict[str, float]:
            values = _training_maxes()
            values.pop("deadlift")
            return values

        def save_full_plan(self, plan_dict: Dict[str, Any]) -> int:
            self.saved = True
            return 42

    dal = StubDal()

    with pytest.raises(PrescriptionValidationError, match="deadlift"):
        PlanService(dal=dal).create_and_persist_531_block(start_date=date(2024, 1, 1))

    assert dal.saved is False


def test_plan_service_repairs_missing_percentage_targets_as_one_bulk_update() -> None:
    class RepairDal(StubPlanRepository):
        def __init__(self) -> None:
            super().__init__()
            self.updates: list[dict[str, Any]] = []

        def get_plan_week_rows(self, plan_id: int, week_number: int):
            assert (plan_id, week_number) == (7, 1)
            return [
                {
                    "id": 101,
                    "week_number": 1,
                    "day_of_week": 1,
                    "exercise_id": schedule_rules.BENCH_ID,
                    "exercise_name": "Bench Press",
                    "sets": 1,
                    "reps": 5,
                    "percent_1rm": 85.0,
                    "target_weight_kg": None,
                    "is_cardio": False,
                },
                {
                    "id": 102,
                    "week_number": 1,
                    "day_of_week": 1,
                    "exercise_id": 301,
                    "exercise_name": "Assistance",
                    "sets": 3,
                    "reps": 10,
                    "percent_1rm": None,
                    "target_weight_kg": None,
                    "is_cardio": False,
                },
            ]

        def update_workout_targets(self, updates):
            self.updates.extend(updates)

    dal = RepairDal()
    result = PlanService(dal=dal).repair_missing_percentage_targets(
        plan_id=7,
        weeks=1,
        recalibrate_training_maxes=False,
    )

    assert dal.updates == [{"workout_id": 101, "target_weight_kg": 102.5}]
    assert result == {
        "plan_id": 7,
        "weeks_checked": 1,
        "workouts_updated": 1,
        "lifts_repaired": ["bench"],
    }


def test_plan_service_does_not_write_a_partial_target_repair() -> None:
    class InvalidRepairDal(StubPlanRepository):
        def __init__(self) -> None:
            super().__init__()
            self.updates: list[dict[str, Any]] = []

        def get_plan_week_rows(self, plan_id: int, week_number: int):
            return [
                {
                    "id": 201,
                    "week_number": 1,
                    "day_of_week": 1,
                    "exercise_id": schedule_rules.BENCH_ID,
                    "exercise_name": "Bench Press",
                    "sets": 1,
                    "reps": 5,
                    "percent_1rm": 85.0,
                    "target_weight_kg": None,
                    "is_cardio": False,
                },
                {
                    "id": 202,
                    "week_number": 1,
                    "day_of_week": 1,
                    "exercise_id": 301,
                    "exercise_name": "Broken Assistance",
                    "sets": None,
                    "reps": 10,
                    "percent_1rm": None,
                    "target_weight_kg": None,
                    "is_cardio": False,
                },
            ]

        def update_workout_targets(self, updates):
            self.updates.extend(updates)

    dal = InvalidRepairDal()

    with pytest.raises(PrescriptionValidationError, match="invalid sets"):
        PlanService(dal=dal).repair_missing_percentage_targets(
            plan_id=7,
            weeks=1,
            recalibrate_training_maxes=False,
        )

    assert dal.updates == []


def test_plan_service_audits_planner_feature_flag_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    audit_events: list[dict[str, Any]] = []

    class StubDal(StubPlanRepository):
        def get_latest_training_maxes(self) -> Dict[str, float]:
            return _training_maxes()

        def save_full_plan(self, plan_dict: Dict[str, Any]) -> int:
            return 99

    service = PlanService(dal=StubDal())

    def stub_create_plan(*args, **kwargs) -> Dict[str, Any]:
        return {
            "start_date": date(2024, 1, 1),
            "weeks": 1,
            "plan_weeks": [{"week_number": 1, "workouts": []}],
            "metadata": {
                "planner_feature_flag_overrides": {
                    "experimental_relaxed_session_spacing": True,
                },
                "planner_feature_flag_effects": [
                    {
                        "week_number": 1,
                        "stage": "feature_flag_experimental_relaxed_session_spacing",
                        "detail": "Experimental relaxed spacing kept quality runs near heavy lower-body strength.",
                        "payload": {
                            "flag": "experimental_relaxed_session_spacing",
                            "affected_sessions": 1,
                        },
                    }
                ],
                "plan_decision_trace": {},
            },
        }

    monkeypatch.setattr(service.factory, "create_unified_531_block_plan", stub_create_plan)
    monkeypatch.setattr(
        "pete_e.application.services.log_utils.log_checkpoint",
        lambda **event: audit_events.append(event),
    )

    assert service.create_and_persist_531_block(start_date=date(2024, 1, 1)) == 99
    assert audit_events == [
        {
            "checkpoint": "planner_feature_flags",
            "outcome": "applied",
            "correlation": {
                "workflow": "plan_generation",
                "start_date": "2024-01-01",
            },
            "summary": {
                "flags": {
                    "experimental_relaxed_session_spacing": True,
                },
                "effects": [
                    {
                        "week_number": 1,
                        "stage": "feature_flag_experimental_relaxed_session_spacing",
                        "detail": "Experimental relaxed spacing kept quality runs near heavy lower-body strength.",
                        "payload": {
                            "flag": "experimental_relaxed_session_spacing",
                            "affected_sessions": 1,
                        },
                    }
                ],
            },
            "tag": "AUDIT",
        }
    ]


def test_plan_service_does_not_audit_inactive_planner_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    audit_events: list[dict[str, Any]] = []

    service = PlanService(dal=StubPlanRepository())

    def stub_create_plan(*args, **kwargs) -> Dict[str, Any]:
        return {
            "start_date": date(2024, 1, 1),
            "weeks": 1,
            "plan_weeks": [{"week_number": 1, "workouts": []}],
            "metadata": {
                "planner_feature_flag_overrides": {},
                "planner_feature_flag_effects": [],
                "plan_decision_trace": {},
            },
        }

    monkeypatch.setattr(service.factory, "create_unified_531_block_plan", stub_create_plan)
    monkeypatch.setattr(
        "pete_e.application.services.log_utils.log_checkpoint",
        lambda **event: audit_events.append(event),
    )

    service.create_and_persist_531_block(start_date=date(2024, 1, 1))
    assert audit_events == []
