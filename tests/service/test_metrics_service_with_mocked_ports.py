from __future__ import annotations

from datetime import date, timedelta

from pete_e.application.api_services import MetricsService
from pete_e.application.profile_service import ProfileService
from pete_e.config import settings
from pete_e.domain.profile import UserProfile


class CoachDal:
    def __init__(self):
        self.base = date(2024, 1, 1)
        """Initialize this object."""

    def get_metrics_overview(self, target_date):
        return ["metric_name"], []
        """Perform get metrics overview."""

    def get_daily_summary(self, target_date):
        return {
            "date": target_date,
            "weight_kg": 89.5,
            "sleep_asleep_minutes": 410,
            "hr_resting": 52,
            "hrv_sdnn_ms": 45,
            "strength_volume_kg": 12000,
            "body_fat_pct": 22.1,
        }
        """Perform get daily summary."""

    def get_historical_data(self, start_date, end_date):
        rows = []
        for offset in range((end_date - start_date).days + 1):
            day = start_date + timedelta(days=offset)
            recent = day >= end_date - timedelta(days=6)
            rows.append(
                {
                    "date": day,
                    "weight_kg": 90.0 if recent else 91.0,
                    "sleep_asleep_minutes": 390 if recent else 420,
                    "hr_resting": 53 if recent else 51,
                    "hrv_sdnn_ms": 44 if recent else 46,
                    "strength_volume_kg": 1000 if recent else 500,
                }
            )
        return rows
        """Perform get historical data."""

    def get_recent_running_workouts(self, *, days, end_date):
        return [
            {
                "workout_date": end_date,
                "workout_type": "Outdoor Run",
                "duration_sec": 1800,
                "total_distance_km": 5.0,
                "pace_min_per_km": 6.0,
            }
        ]
        """Perform get recent running workouts."""

    def get_recent_strength_workouts(self, *, days, end_date):
        return [
            {
                "workout_date": end_date,
                "exercise_name": "Squat",
                "sets": 3,
                "reps": 15,
                "volume_kg": 1500,
            }
        ]
        """Perform get recent strength workouts."""

    def get_nutrition_daily_summaries(self, start_date, end_date):
        return [
            {
                "date": end_date,
                "protein_g": 120,
                "carbs_g": 180,
                "fat_g": 70,
                "alcohol_g": 15,
                "fiber_g": 20,
                "calories_est": 1830,
                "meals_logged": 3,
            }
        ]
        """Perform get nutrition daily summaries."""

    def get_active_plan(self):
        return {"id": 10, "start_date": date(2024, 1, 1), "weeks": 4, "is_active": True}
        """Perform get active plan."""

    def get_latest_training_maxes(self):
        return {"squat": 120}
        """Perform get latest training maxes."""

    def get_latest_training_max_date(self):
        return date(2023, 12, 15)
        """Perform get latest training max date."""
    """Represent CoachDal."""


class ProfileRepo:
    def get_default_profile(self):
        return UserProfile(
            id=2,
            slug="athlete",
            display_name="Athlete",
            goal_weight_kg=82,
            height_cm=180,
            timezone="Europe/London",
            is_default=True,
        )

    def get_profile_by_slug(self, slug):
        if slug == "athlete":
            return self.get_default_profile()
        return None

    def list_profiles_for_user(self, user_id):
        return [self.get_default_profile()]

    def list_profiles(self):
        return [self.get_default_profile()]


def test_daily_summary_adds_units_sources_and_quality():
    payload = MetricsService(CoachDal()).daily_summary("2024-01-08")

    assert payload["metrics"]["weight_kg"]["unit"] == "kg"
    assert payload["metrics"]["weight_kg"]["source"] == "withings_or_body_age"
    assert payload["metrics"]["body_fat_pct"]["trust_level"] == "low"
    assert payload["data_quality"]["status"] == "complete"
    """Perform test daily summary adds units sources and quality."""


def test_coach_state_exposes_derived_flags_and_context():
    payload = MetricsService(CoachDal()).coach_state("2024-01-08")

    assert payload["derived"]["run_load_7d_km"] == 5.0
    assert payload["derived"]["strength_load_7d_kg"] == 7000.0
    assert payload["summary"]["readiness_state"] in {"green", "amber", "red"}
    assert payload["plan_context"]["current_week_number"] == 2
    assert payload["nutrition"]["data_quality"]["nutrition_data_quality"] == "partial"
    assert payload["nutrition"]["last_7d"]["avg_alcohol_g"] == 15.0
    assert payload["nutrition"]["last_7d"]["avg_fiber_g"] == 20.0
    assert payload["goal_state"]["strength"]["training_maxes_kg"] == {"squat": 120}
    """Perform test coach state exposes derived flags and context."""


def test_goal_state_keeps_settings_backed_default_without_profile_repository():
    payload = MetricsService(CoachDal()).goal_state()

    assert payload["profile"]["slug"] == "default"
    assert payload["body_composition_goal"]["goal_weight_kg"] == settings.USER_GOAL_WEIGHT_KG


def test_goal_state_can_use_database_backed_profile():
    service = MetricsService(CoachDal(), profile_service=ProfileService(ProfileRepo()))

    payload = service.goal_state(profile_slug="athlete")

    assert payload["profile"]["slug"] == "athlete"
    assert payload["body_composition_goal"]["goal_weight_kg"] == 82
    assert payload["body_composition_goal"]["height_cm"] == 180
