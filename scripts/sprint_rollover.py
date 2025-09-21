import datetime
from pete_e.application.orchestrator import Orchestrator
from pete_e.infrastructure import log_utils

def is_4th_sunday(today=None) -> bool:
    today = today or datetime.date.today()
    # ISO week number modulo 4 == 0 => sprint rollover
    return today.isoweekday() == 7 and (today.isocalendar()[1] % 4 == 0)

def main():
    orch = Orchestrator()
    today = datetime.date.today()
    if is_4th_sunday(today):
        result = orch.run_cycle_rollover(reference_date=today, weeks=4)
        if result.exported:
            log_utils.log_message("Sprint rollover complete, week 1 exported to Wger.", "INFO")
        elif result.plan_id:
            log_utils.log_message("Sprint rollover detected existing plan/export; nothing to do.", "INFO")
        else:
            log_utils.log_message("Sprint rollover failed to prepare next cycle.", "ERROR")
    else:
        log_utils.log_message("Not a sprint rollover Sunday, exiting.", "INFO")

if __name__ == "__main__":
    main()
