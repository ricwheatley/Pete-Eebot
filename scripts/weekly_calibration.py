from pete_e.application.orchestrator import Orchestrator
from pete_e.domain.narrative_builder import PeteVoice
from pete_e.infrastructure import log_utils

def main():
    orch = Orchestrator()
    # TODO: add actual calibration logic here if needed
    msg = PeteVoice.nudge("#PlanCheck", ["I’ve reviewed last week’s logs and adjusted the plan"])
    orch.send_telegram_message(msg)
    log_utils.log_message("Weekly calibration complete and confirmation sent.", "INFO")

if __name__ == "__main__":
    main()
