import pytest
import sys
import types
from datetime import date, timedelta
from pathlib import Path

# Provide lightweight stubs for heavy dependencies imported during plan builder
# module initialisation. This keeps the tests self-contained and avoids pulling
# in optional runtime-only packages.
config_stub = types.ModuleType("pete_e.config")


class _StubSettings:
    def __init__(self):
        self.log_path = Path("/tmp/pete_eebot-test.log")


config_stub.Settings = _StubSettings
config_stub.settings = _StubSettings()
sys.modules.setdefault("pete_e.config", config_stub)
sys.modules.setdefault("pete_e.config.config", config_stub)

psycopg_stub = types.ModuleType("psycopg")


def _stub_connect(*_args, **_kwargs):
    raise RuntimeError("psycopg stub does not support database connections")


psycopg_stub.connect = _stub_connect

conninfo_module = types.ModuleType("psycopg.conninfo")
conninfo_module.make_conninfo = lambda *_args, **_kwargs: ""

rows_module = types.ModuleType("psycopg.rows")


def _stub_dict_row(_cursor):  # pragma: no cover - defensive stub
    raise RuntimeError("psycopg.rows.dict_row is unavailable in tests")


rows_module.dict_row = _stub_dict_row

json_module = types.ModuleType("psycopg.types.json")


class Json:  # pragma: no cover - behaviour is not exercised in tests
    def __init__(self, data):
        self.data = data


types_module = types.ModuleType("psycopg.types")
json_module.Json = Json
types_module.json = json_module

psycopg_stub.conninfo = conninfo_module
psycopg_stub.rows = rows_module
psycopg_stub.types = types_module

sys.modules.setdefault("psycopg", psycopg_stub)
sys.modules.setdefault("psycopg.conninfo", conninfo_module)
sys.modules.setdefault("psycopg.rows", rows_module)
sys.modules.setdefault("psycopg.types", types_module)
sys.modules.setdefault("psycopg.types.json", json_module)

from pete_e.domain import plan_builder, schedule_rules
from pete_e.infrastructure import plan_rw


class DummyDAL:
    """Fake DAL to simulate pool lookups without hitting DB."""

    def __init__(self):
        self.assist_calls = []
        self.saved_plans = []
        self.saved_workouts = []

    def get_active_plan(self):
        return None

    # mimic plan_rw API
    def assistance_pool_for(self, main_id):
        # Return fake IDs based on main lift
        self.assist_calls.append(main_id)
        return [100 + main_id, 200 + main_id, 300 + main_id]

    def core_pool_ids(self):
        return [999, 998, 997]

    def create_block_and_plan(self, start_date, weeks=4):
        return 1, list(range(1, weeks + 1))

    def insert_workout(
        self,
        week_id,
        day_of_week,
        exercise_id,
        sets,
        reps,
        rir_cue,
        percent_1rm,
        target_weight_kg,
        scheduled_time,
        is_cardio,
    ):
        self.saved_workouts.append(
            dict(
                week_id=week_id,
                day_of_week=day_of_week,
                exercise_id=exercise_id,
                sets=sets,
                reps=reps,
                rir=rir_cue,
                pct=percent_1rm,
                target_weight_kg=target_weight_kg,
                time=scheduled_time,
                cardio=is_cardio,
            )
        )

    def plan_week_rows(self, plan_id, week_number):
        return self.saved_workouts


@pytest.fixture
def dal(monkeypatch):
    dummy = DummyDAL()
    # Patch plan_rw functions to dummy
    monkeypatch.setattr(plan_rw, "create_block_and_plan", dummy.create_block_and_plan)
    monkeypatch.setattr(plan_rw, "insert_workout", dummy.insert_workout)
    monkeypatch.setattr(plan_rw, "assistance_pool_for", dummy.assistance_pool_for)
    monkeypatch.setattr(plan_rw, "core_pool_ids", dummy.core_pool_ids)
    monkeypatch.setattr(plan_rw, "get_active_plan", dummy.get_active_plan)
    monkeypatch.setattr(plan_rw, "plan_week_rows", dummy.plan_week_rows)
    return dummy


def test_block_structure(dal, monkeypatch):
    monkeypatch.setattr(
        plan_rw,
        "latest_training_max",
        lambda: {
            "squat": 100.0,
            "bench": 80.0,
            "deadlift": 120.0,
            "ohp": 60.0,
        },
    )

    start = date(2025, 1, 6)  # a Monday
    plan_id = plan_builder.build_training_block(start, weeks=4)

    assert plan_id == 1
    workouts = dal.saved_workouts

    # There should be 4 weeks * 4 days * (Blaze + main + 2 assist + core) = 64 workouts
    assert len(workouts) == 4 * 4 * 5

    # Blaze always inserted, with id=1630
    blaze_ids = [w["exercise_id"] for w in workouts if w["cardio"]]
    assert all(x == schedule_rules.BLAZE_ID for x in blaze_ids)

    # Each main lift appears once per week on the right day
    for dow, main_id in schedule_rules.MAIN_LIFT_BY_DOW.items():
        for week in range(1, 5):
            found = [
                w for w in workouts if w["week_id"] == week and w["day_of_week"] == dow and not w["cardio"]
            ]
            main_lifts = [w for w in found if w["exercise_id"] == main_id]
            assert main_lifts, f"Week {week} dow {dow} missing main {main_id}"

            # Verify %1RM matches schedule_rules.WEEK_PCTS
            scheme = schedule_rules.WEEK_PCTS[week]
            assert main_lifts[0]["pct"] == scheme["percent_1rm"]

    # Deload week (4) should have reduced assistance/core sets
    week4 = [w for w in workouts if w["week_id"] == 4 and not w["cardio"]]
    non_mains = [w for w in week4 if w["exercise_id"] not in schedule_rules.MAIN_LIFT_BY_DOW.values()]
    for w in non_mains:
        assert w["sets"] < 3 or w["sets"] < schedule_rules.ASSISTANCE_1["sets"]

    # Week 1 main lifts should have target weights derived from training maxes
    tm_map = plan_rw.latest_training_max()
    week1_pct = schedule_rules.WEEK_PCTS[1]["percent_1rm"]
    expected_targets = {}
    for exercise_id, lift_code in schedule_rules.LIFT_CODE_BY_ID.items():
        if lift_code in tm_map:
            expected_targets[exercise_id] = round(
                tm_map[lift_code] * week1_pct / 100 / 2.5
            ) * 2.5

    week1_main_lifts = [
        w
        for w in workouts
        if w["week_id"] == 1
        and not w["cardio"]
        and w["exercise_id"] in schedule_rules.MAIN_LIFT_BY_DOW.values()
    ]
    assert week1_main_lifts, "Expected to find main lifts for week 1"
    for workout in week1_main_lifts:
        expected = expected_targets[workout["exercise_id"]]
        assert workout["target_weight_kg"] == expected
