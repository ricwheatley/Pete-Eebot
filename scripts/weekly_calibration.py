from pete_e.application.orchestrator import Orchestrator
from pete_e.domain.narrative_builder import PeteVoice
from pete_e.infrastructure import log_utils


def main() -> None:
    orch = Orchestrator()
    result = orch.run_weekly_calibration()

    telegram_line = PeteVoice.nudge("#PlanCheck", [result.message])
    try:
        orch.send_telegram_message(telegram_line)
    except Exception as exc:
        log_utils.log_message(f"Failed to send weekly calibration message: {exc}", "ERROR")
    else:
        log_utils.log_message(
            f"Weekly calibration message sent for week {result.week_number or 'n/a'}.",
            "INFO",
        )


if __name__ == "__main__":
    main()
