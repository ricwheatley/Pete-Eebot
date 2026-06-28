from __future__ import annotations

import tests.config_stub  # noqa: F401

from pete_e.application.catalog_sync import CatalogSyncService
from pete_e.domain import schedule_rules


def test_catalog_sync_seeds_programming_metadata_without_overwriting() -> None:
    calls: list[tuple[str, object]] = []

    class StubDal:
        def upsert_wger_categories(self, rows):
            calls.append(("categories", rows))

        def upsert_wger_equipment(self, rows):
            calls.append(("equipment", rows))

        def upsert_wger_muscles(self, rows):
            calls.append(("muscles", rows))

        def upsert_wger_exercises_and_relations(self, rows):
            calls.append(("exercises", rows))

        def seed_main_lifts(self, main_lift_ids):
            calls.append(("main_lifts", main_lift_ids))

        def seed_default_exercise_programming_metadata(self, *, assistance_pool_data, core_pool_data):
            calls.append(("metadata_defaults", (assistance_pool_data, core_pool_data)))

        def seed_exercise_programming_metadata(self, exercise_ids):
            calls.append(("metadata_missing", exercise_ids))

        def close(self):
            calls.append(("close", None))

    class StubClient:
        def get_all_pages(self, path):
            if path == "/exercisecategory/":
                return [{"id": 8, "name": "Arms"}]
            if path == "/equipment/":
                return [{"id": 1, "name": "Body weight"}]
            if path == "/muscle/":
                return [{"id": 1, "name": "Abs"}]
            if path == "/exerciseinfo/":
                return [
                    {
                        "id": 458,
                        "uuid": "00000000-0000-0000-0000-000000000458",
                        "translations": [{"language": 2, "name": "Plank", "description": ""}],
                        "category": {"id": 10},
                        "equipment": [{"id": 1}],
                        "muscles": [{"id": 1}],
                        "muscles_secondary": [],
                    }
                ]
            raise AssertionError(f"unexpected path {path}")

    service = CatalogSyncService(dal_factory=StubDal, wger_client_factory=StubClient)

    service.run()

    assert ("main_lifts", schedule_rules.MAIN_LIFT_IDS) in calls
    assert (
        "metadata_defaults",
        (schedule_rules.ASSISTANCE_POOL_DATA, schedule_rules.DEFAULT_CORE_POOL_DATA),
    ) in calls
    assert ("metadata_missing", [458]) in calls
    assert calls[-1] == ("close", None)
