import datetime
from pete_e.application.orchestrator import Orchestrator
from pete_e.infrastructure import log_utils


def is_4th_sunday(today=None) -> bool:
    """
    Determine if today is a sprint rollover Sunday.
    ISO week number modulo 4 == 0 triggers a new 4-week cycle.
    """
    today = today or datetime.date.today()
    return today.isoweekday() == 7 and (today.isocalendar()[1] % 4 == 0)


def main():
    orch = Orchestrator()
    today = datetime.date.today()

    # --- 🧠 Determine what kind of plan to generate ---
    last_plan = None
    try:
        last_plan = orch.get_active_plan()
    except AttributeError:
        log_utils.log_message(
            "Orchestrator has no get_active_plan(); cannot inspect last plan.", "WARNING"
        )

    # Default plan parameters
    plan_weeks = 4
    plan_type = "standard"

    if last_plan:
        last_weeks = getattr(last_plan, "weeks", 4)
        last_type = getattr(last_plan, "type", "").lower()

        # If the previous plan was a single-week strength test,
        # force a 4-week standard mesocycle next.
        if last_weeks == 1 or "strength_test" in last_type:
            plan_weeks = 4
            plan_type = "standard"
            log_utils.log_message(
                "Previous plan was a 1-week strength test — generating new 4-week standard plan.",
                "INFO",
            )
        else:
            # Normal 4-week rollover continues
            plan_weeks = 4
            plan_type = "standard"
            log_utils.log_message("Continuing normal 4-week sprint cycle.", "INFO")

    # --- 🗓️ Execute rollover only on 4th Sunday ---
    if is_4th_sunday(today):
        result = orch.run_cycle_rollover(reference_date=today, weeks=plan_weeks, plan_type=plan_type)

        if result.exported:
            log_utils.log_message("Sprint rollover complete — week 1 exported to Wger.", "INFO")
        elif result.plan_id:
            log_utils.log_message("Sprint rollover detected existing plan/export; nothing to do.", "INFO")
        else:
            log_utils.log_message("Sprint rollover failed to prepare next cycle.", "ERROR")
    else:
        log_utils.log_message("Not a sprint rollover Sunday, exiting.", "INFO")


if __name__ == "__main__":
    main()
