import datetime
from pete_e.core.orchestrator import Orchestrator
from pete_e.core.narrative_builder import PeteVoice
from pete_e.infra import log_utils

def is_4th_sunday(today=None) -> bool:
    today = today or datetime.date.today()
    # ISO week number modulo 4 == 0 => sprint rollover
    return today.isoweekday() == 7 and (today.isocalendar()[1] % 4 == 0)

def main():
    orch = Orchestrator()
    if is_4th_sunday():
        # TODO: hook into plan generation logic
        plan_id = orch.generate_and_deploy_next_plan(start_date=datetime.date.today() + datetime.timedelta(days=1), weeks=4)
        if plan_id > 0:
            msg = PeteVoice.nudge("#SprintComplete", ["I’ve reviewed the cycle, created the new block, and posted Week 1 to Wger"])
            orch.send_telegram_message(msg)
            log_utils.log_message(f"Sprint rollover complete, plan {plan_id} deployed.", "INFO")
        else:
            log_utils.log_message("Sprint rollover failed to generate plan.", "ERROR")
    else:
        log_utils.log_message("Not a sprint rollover Sunday, exiting.", "INFO")

if __name__ == "__main__":
    main()
