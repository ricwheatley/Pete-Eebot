"""Application service responsible for syncing the wger catalog."""

from __future__ import annotations

from typing import Callable

from pete_e.domain import schedule_rules
from pete_e.infrastructure import log_utils
from pete_e.infrastructure.postgres_dal import PostgresDal
from pete_e.infrastructure.wger_client import WgerClient



STANDARD_EQUIPMENT_NAMES = {
    "barbell",
    "bench",
    "body weight",
    "bodyweight",
    "dumbbell",
    "gym mat",
    "mat",
    "none",
    "pull-up bar",
}


def _equipment_name_map(equipment: list[dict]) -> dict[int, str]:
    return {
        int(item["id"]): str(item.get("name") or "").strip().lower()
        for item in equipment
        if item.get("id") is not None
    }


def _has_only_standard_equipment(exercise: dict, equipment_names: dict[int, str]) -> bool:
    exercise_equipment = exercise.get("equipment") or []
    if not exercise_equipment:
        return True
    names = [equipment_names.get(int(eq["id"]), "") for eq in exercise_equipment if eq.get("id") is not None]
    return bool(names) and all(name in STANDARD_EQUIPMENT_NAMES for name in names)

class CatalogSyncService:
    """Refreshes the local wger catalog and seeds assistance metadata."""

    def __init__(
        self,
        dal_factory: Callable[[], PostgresDal] | None = None,
        wger_client_factory: Callable[[], WgerClient] | None = None,
    ) -> None:
        self._dal_factory = dal_factory or PostgresDal
        self._wger_client_factory = wger_client_factory or WgerClient
        """Initialize this object."""

    def run(self) -> None:
        """Execute the full catalog refresh workflow."""
        log_utils.info("Starting WGER catalogue refresh...")
        dal = self._dal_factory()
        client = self._wger_client_factory()

        try:
            categories = client.get_all_pages("/exercisecategory/")
            equipment = client.get_all_pages("/equipment/")
            muscles = client.get_all_pages("/muscle/")
            exercises_raw = client.get_all_pages("/exerciseinfo/")

            equipment_names = _equipment_name_map(equipment)
            protected_ids = set(schedule_rules.MAIN_LIFT_IDS) | {schedule_rules.BLAZE_ID, schedule_rules.TREADMILL_RUN_ID, schedule_rules.OUTDOOR_RUN_ID}
            processed_exercises = []
            for exercise in exercises_raw:
                translations = exercise.get("translations") or []
                en_translation = next((t for t in translations if t.get("language") == 2 and t.get("name")), None)
                exercise_id = exercise.get("id")
                if not en_translation and exercise_id not in protected_ids:
                    continue
                if exercise_id not in protected_ids and not _has_only_standard_equipment(exercise, equipment_names):
                    continue
                en_translation = en_translation or {}
                processed_exercises.append(
                    {
                        "id": exercise.get("id"),
                        "uuid": exercise.get("uuid"),
                        "name": en_translation.get("name", "Unknown"),
                        "description": en_translation.get("description", ""),
                        "category_id": (exercise.get("category") or {}).get("id"),
                        "equipment_ids": [eq.get("id") for eq in exercise.get("equipment", []) if eq.get("id")],
                        "primary_muscle_ids": [m.get("id") for m in exercise.get("muscles", []) if m.get("id")],
                        "secondary_muscle_ids": [m.get("id") for m in exercise.get("muscles_secondary", []) if m.get("id")],
                    }
                )

            dal.upsert_wger_categories(categories)
            dal.upsert_wger_equipment(equipment)
            dal.upsert_wger_muscles(muscles)
            dal.upsert_wger_exercises_and_relations(processed_exercises)

            dal.seed_main_lifts(schedule_rules.MAIN_LIFT_IDS)
            dal.seed_default_exercise_programming_metadata(
                assistance_pool_data=schedule_rules.ASSISTANCE_POOL_DATA,
                core_pool_data=schedule_rules.DEFAULT_CORE_POOL_DATA,
            )
            dal.seed_exercise_programming_metadata(
                [
                    int(exercise["id"])
                    for exercise in processed_exercises
                    if exercise.get("id") is not None
                ]
            )

            log_utils.info("WGER catalogue refresh completed successfully.")
        except Exception as exc:  # noqa: BLE001 - broad exception mirrors CLI behaviour
            log_utils.error(f"Catalogue refresh failed: {exc}", exc_info=True)
            raise
        finally:
            dal.close()
