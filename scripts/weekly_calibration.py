from pete_e.application.orchestrator import Orchestrator
from pete_e.domain.narrative_builder import PeteVoice
from pete_e.infrastructure import log_utils


def main() -> None:
    """
    Weekly calibration entry point.

    Adds safety guards to prevent calibration from running
    on short (1-week) or 'strength_test' plans, and ensures
    Telegram notifications still go out cleanly.
    """
    orch = Orchestrator()

    # --- 🧩 Safety Guard ---
    try:
        active_plan = orch.get_active_plan()
    except AttributeError:
        log_utils.log_message("Orchestrator missing get_active_plan(); cannot verify plan length.", "WARNING")
        active_plan = None

    if not active_plan:
        log_utils.log_message("No active plan found — skipping calibration.", "WARNING")
        return

    plan_type = getattr(active_plan, "type", "")
    plan_weeks = getattr(active_plan, "weeks", None)

    if plan_weeks is None:
        log_utils.log_message(f"Active plan {getattr(active_plan, 'id', '?')} has no 'weeks' attribute.", "WARNING")
        return

    if plan_weeks <= 1 or plan_type == "strength_test":
        log_utils.log_message(
            f"Skipping calibration for plan {getattr(active_plan, 'id', '?')} — "
            f"single-week or strength-test plan detected.",
            "INFO",
        )
        return

    # --- 🧠 Proceed with calibration if multi-week plan ---
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