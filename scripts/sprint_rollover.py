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
    plan_weeks = 4
    plan_type = "standard"

    try:
        last_plan = getattr(orch, "get_active_plan", lambda: None)()
    except Exception as exc:
        log_utils.log_message(f"Unable to inspect last plan: {exc}", "WARNING")
        last_plan = None

    if last_plan:
        last_weeks = getattr(last_plan, "weeks", 4)
        last_type = getattr(last_plan, "type", "").lower()

        if last_weeks == 1 or "strength_test" in last_type:
            plan_weeks = 4
            plan_type = "standard"
            log_utils.log_message(
                "Previous plan was a 1-week strength test — generating new 4-week standard plan.",
                "INFO",
            )
        else:
            log_utils.log_message("Continuing normal 4-week sprint cycle.", "INFO")
    else:
        log_utils.log_message("Could not read last plan; defaulting to 4-week standard plan.", "WARNING")

    # --- 🗓️ Execute rollover only on 4th Sunday ---
    if is_4th_sunday(today):
        # run_cycle_rollover only accepts reference_date and weeks
        result = orch.run_cycle_rollover(reference_date=today, weeks=plan_weeks)

        # After rollover, explicitly update the plan type if required
        try:
            if hasattr(result, "plan_id") and result.plan_id and plan_type != "strength_test":
                orch.set_plan_type(result.plan_id, plan_type)
                log_utils.log_message(f"Set plan {result.plan_id} type to '{plan_type}'.", "INFO")
        except Exception as exc:
            log_utils.log_message(f"Failed to update plan type: {exc}", "WARNING")

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
