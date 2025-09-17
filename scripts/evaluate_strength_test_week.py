# scripts/evaluate_strength_test_week.py
#
# Evaluate the most recent strength-test week (is_test=true),
# compute e1RM via Epley and upsert Training Maxes.

from pete_e.core.strength_test_v1 import evaluate_test_week_and_update_tms

def main():
    res = evaluate_test_week_and_update_tms()
    print(res or {"status": "no-test-week-found"})

if __name__ == "__main__":
    main()
