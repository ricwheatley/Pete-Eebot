"""Application service responsible for syncing the wger catalog."""

from __future__ import annotations

from typing import Callable

from pete_e.domain import schedule_rules
from pete_e.infrastructure import log_utils
from pete_e.infrastructure.postgres_dal import PostgresDal
from pete_e.infrastructure.wger_client import WgerClient


class CatalogSyncService:
    """Refreshes the local wger catalog and seeds assistance metadata."""

    def __init__(
        self,
        dal_factory: Callable[[], PostgresDal] | None = None,
        wger_client_factory: Callable[[], WgerClient] | None = None,
    ) -> None:
        self._dal_factory = dal_factory or PostgresDal
        self._wger_client_factory = wger_client_factory or WgerClient

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

            processed_exercises = []
            for exercise in exercises_raw:
                translations = exercise.get("translations") or []
                en_translation = next((t for t in translations if t.get("language") == 2), None) or {}
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

            dal.seed_main_lifts_and_assistance(
                main_lift_ids=schedule_rules.MAIN_LIFT_IDS,
                assistance_pool_data=schedule_rules.ASSISTANCE_POOL_DATA,
            )

            log_utils.info("WGER catalogue refresh completed successfully.")
        except Exception as exc:  # noqa: BLE001 - broad exception mirrors CLI behaviour
            log_utils.error(f"Catalogue refresh failed: {exc}", exc_info=True)
            raise
        finally:
            dal.close()
