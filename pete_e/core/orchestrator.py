"""
Main orchestrator for Pete-Eebot's core logic.
"""
from datetime import date, timedelta
from typing import Dict, Any, List, Tuple

# DAL and Clients
from pete_e.data_access.dal import DataAccessLayer
from pete_e.data_access.postgres_dal import PostgresDal
from pete_e.core.withings_client import WithingsClient
from pete_e.core.wger_client import WgerClient
from pete_e.core import apple_client, body_age

# Core Logic and Helpers
from pete_e.core.narrative_builder import NarrativeBuilder
from pete_e.core.plan_builder import PlanBuilder
from pete_e.domain.user_helpers import calculate_age
from pete_e.infra import log_utils, telegram_sender
from pete_e.config import settings

class Orchestrator:
    """
    Handles the main business logic and coordination between different parts
    of the application.
    """

    def __init__(self, dal: DataAccessLayer = None):
        self.dal = dal or PostgresDal()
        self.narrative_builder = NarrativeBuilder()

    def get_daily_summary(self, target_date: date = None) -> str:
        """
        Generates a human-readable summary for a given day.
        Fetches the latest data from the DB and uses NarrativeBuilder to format it.
        """
        if target_date is None:
            target_date = date.today() - timedelta(days=1) # Default to yesterday

        log_utils.log_message(f"Generating daily summary for {target_date.isoformat()}", "INFO")
        summary_data = self.dal.get_daily_summary(target_date)

        if not summary_data:
            return f"I have no data for {target_date.strftime('%A, %B %d')}. Something might have gone wrong with the daily sync."

        return self.narrative_builder.build_daily_summary(summary_data)


    def get_week_plan_summary(self, target_date: date = None) -> str:
        """
        Generates a human-readable summary of the current week's training plan.
        """
        if target_date is None:
            target_date = date.today()

        log_utils.log_message(f"Generating weekly plan summary for week of {target_date.isoformat()}", "INFO")
        
        # Note: You will need to implement `get_active_plan` and `get_plan_week` in your DAL
        active_plan = self.dal.get_active_plan()
        if not active_plan:
            return "There is no active training plan in the database."

        # Calculate the week number
        days_since_start = (target_date - active_plan['start_date']).days
        if days_since_start < 0:
            return f"The active training plan starts on {active_plan['start_date'].isoformat()}."
        
        week_number = (days_since_start // 7) + 1
        if week_number > active_plan['weeks']:
            return "The current training plan has finished. Time to generate a new one!"

        plan_week_data = self.dal.get_plan_week(active_plan['id'], week_number)
        if not plan_week_data:
            return f"Could not find workout data for Plan ID {active_plan['id']}, Week {week_number}."

        return self.narrative_builder.build_weekly_plan(plan_week_data, week_number)


    def send_telegram_message(self, message: str) -> None:
        """Sends a message using the Telegram sender."""
        telegram_sender.send_message(message)

    def run_daily_sync(self, days: int) -> Tuple[bool, List[str]]:
        """
        Orchestrates the daily data synchronization process.

        This method fetches data from all external sources, saves it to the
        database, and triggers necessary recalculations.
        """
        today = date.today()
        log_utils.log_message(f"Orchestrator starting sync for last {days} days.", "INFO")

        withings_client = WithingsClient()
        wger_client = WgerClient() # Assuming a WgerClient class exists

        failed_sources: List[str] = []
        try:
            wger_logs_by_date = wger_client.get_logs_by_date(days=days)
        except Exception as e:
            log_utils.log_message(
                f"Failed to retrieve Wger logs for sync window ({days} days): {e}",
                "ERROR",
            )
            failed_sources.append("Wger")
            wger_logs_by_date = {}

        wger_logs_found = False

        for offset in range(days, 0, -1):
            target_day = today - timedelta(days=offset)
            target_iso = target_day.isoformat()
            log_utils.log_message(f"Syncing data for {target_iso}", "INFO")

            # --- Withings ---
            try:
                withings_data = withings_client.get_summary(days_back=offset)
                if withings_data:
                    self.dal.save_withings_daily(
                        day=target_day,
                        weight_kg=withings_data.get("weight"),
                        body_fat_pct=withings_data.get("fat_percent"),
                    )
            except Exception as e:
                log_utils.log_message(f"Withings sync failed for {target_iso}: {e}", "ERROR")
                failed_sources.append("Withings")

            # --- Apple Health ---
            try:
                apple_data = apple_client.get_apple_summary({"date": target_iso})
                if apple_data:
                    self.dal.save_apple_daily(target_day, apple_data)
            except Exception as e:
                log_utils.log_message(f"Apple Health sync failed for {target_iso}: {e}", "ERROR")
                failed_sources.append("AppleHealth")

            # --- Wger Workout Logs ---
            try:
                day_logs = wger_logs_by_date.get(target_iso, [])
                if day_logs:
                    wger_logs_found = True
                    for i, log in enumerate(day_logs, start=1):
                        self.dal.save_wger_log(
                            day=target_day,
                            exercise_id=log.get("exercise_id"),
                            set_number=i,
                            reps=log.get("reps"),
                            weight_kg=log.get("weight"),
                            rir=log.get("rir"),
                        )
            except Exception as e:
                log_utils.log_message(f"Wger sync failed for {target_iso}: {e}", "ERROR")
                failed_sources.append("Wger")

            # --- Body Age Recalculation ---
            try:
                self._recalculate_body_age(target_day)
            except Exception as e:
                log_utils.log_message(f"Body Age calculation failed for {target_iso}: {e}", "ERROR")
                failed_sources.append("BodyAge")


        if wger_logs_found:
            log_utils.log_message("Refreshing actual muscle volume view...", "INFO")
            self.dal.refresh_actual_view()

        return not failed_sources, sorted(list(set(failed_sources)))


    def _recalculate_body_age(self, target_day: date) -> None:
        """Helper to calculate and save body age for a specific day."""
        hist_data = self.dal.get_historical_data(
            start_date=target_day - timedelta(days=6),
            end_date=target_day,
        )

        withings_history = [{"weight": r.get("weight_kg"), "fat_percent": r.get("body_fat_pct")} for r in hist_data]
        apple_history = [{"steps": r.get("steps"), "exercise_minutes": r.get("exercise_minutes"), "calories_active": r.get("calories_active"), "calories_resting": r.get("calories_resting"), "stand_minutes": r.get("stand_minutes"), "distance_m": r.get("distance_m"), "hr_resting": r.get("hr_resting"), "hr_avg": r.get("hr_avg"), "hr_max": r.get("hr_max"), "hr_min": r.get("hr_min"), "sleep_total_minutes": r.get("sleep_total_minutes"), "sleep_asleep_minutes": r.get("sleep_asleep_minutes"), "sleep_rem_minutes": r.get("sleep_rem_minutes"), "sleep_deep_minutes": r.get("sleep_deep_minutes"), "sleep_core_minutes": r.get("sleep_core_minutes"), "sleep_awake_minutes": r.get("sleep_awake_minutes")} for r in hist_data]

        user_age = calculate_age(settings.USER_DATE_OF_BIRTH, on_date=target_day)

        result = body_age.calculate_body_age(
            withings_history=withings_history,
            apple_history=apple_history,
            profile={"age": user_age},
        )

        if result:
            self.dal.save_body_age_daily(target_day, result)
        else:
            log_utils.log_message(f"No body age result for {target_day.isoformat()}", "WARN")

    def generate_and_deploy_next_plan(self, start_date: date, weeks: int) -> int:
        """
        Builds and deploys a new multi-week training plan.

        This is the core planning function of the application, intended to be
        run at the end of a training cycle.

        Args:
            start_date: The start date for the new plan.
            weeks: The number of weeks the plan should last.

        Returns:
            The ID of the newly created plan.
        """
        log_utils.log_message(f"Generating new {weeks}-week plan starting {start_date.isoformat()}", "INFO")

        try:
            # 1. Build the plan structure using PlanBuilder
            builder = PlanBuilder()
            plan_dict = builder.build_plan(weeks=weeks) # Assuming a method like this exists
            log_utils.log_message("Successfully built plan structure.", "INFO")

            # 2. Save the plan to the database via the DAL
            plan_id = self.dal.save_training_plan(plan=plan_dict, start_date=start_date)
            log_utils.log_message(f"Successfully saved new plan with ID: {plan_id}", "INFO")

            # 3. Refresh the plan view to include the new data
            self.dal.refresh_plan_view()

            return plan_id

        except Exception as e:
            log_utils.log_message(f"Failed to generate and deploy new plan: {e}", "ERROR")
            return -1 # Return a sentinel value indicating failure