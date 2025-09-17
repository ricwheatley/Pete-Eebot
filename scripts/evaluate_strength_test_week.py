# scripts/evaluate_strength_test_week.py
#
# Evaluate the most recent strength-test week (is_test=true),
# compute e1RM via Epley and upsert Training Maxes.
# Then re-export the test week to wger with proper logging.

from datetime import timedelta

from pete_e.core.strength_test_v1 import evaluate_test_week_and_update_tms
from pete_e.data_access.plan_rw import latest_test_week, build_week_payload
from pete_e.core.wger_exporter_v3 import export_week_to_wger


def main():
    # Run evaluator – updates strength_test_result and training_max
    res = evaluate_test_week_and_update_tms()
    print(res or {"status": "no-test-week-found"})

    # If we found and evaluated a test week, re-export it to Wger
    if res and res.get("status") == "ok":
        tw = latest_test_week()
        if tw:
            plan_id = tw["plan_id"]
            week_number = tw["week_number"]
            start_date = tw["start_date"]
            week_start = start_date + timedelta(days=(week_number - 1) * 7)
            week_end = week_start + timedelta(days=6)

            payload = build_week_payload(plan_id, week_number)
            created = export_week_to_wger(payload, week_start=week_start, week_end=week_end)
            print("\nWger routine updated after TM recalibration:")
            print(created)


if __name__ == "__main__":
    main()
