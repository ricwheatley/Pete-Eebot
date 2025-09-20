# pete_e/domain/schedule_rules.py

from datetime import time

# Big Four exercise IDs from your data set
SQUAT_ID = 615
BENCH_ID = 73
DEADLIFT_ID = 184
OHP_ID = 566

# Blaze is a fixed HIIT class logged as this id
BLAZE_ID = 99999

# Blaze class start times by weekday (1=Mon ... 7=Sun)
BLAZE_TIMES = {
    1: time(6, 15),  # Mon
    2: time(7, 0),   # Tue
    3: time(7, 0),   # Wed
    4: time(6, 15),  # Thu
    5: time(7, 15),  # Fri
}

# We treat Blaze duration as 45 minutes. We only store start time in DB.
BLAZE_DURATION_MIN = 45

# Your lifting preference:
# - On Blaze-first days (Mon, Thu) we lift after Blaze.
# - On Weights-first days (Tue, Fri) we lift before Blaze.
def weight_slot_for_day(dow: int) -> time:
    """Return the scheduled start time for weights on the given weekday (1..7)."""
    if dow == 1:   # Mon, Blaze 06:15 -> weights 07:05
        return time(7, 5)
    if dow == 2:   # Tue, weights first 06:00
        return time(6, 0)
    if dow == 4:   # Thu, Blaze 06:15 -> weights 07:05
        return time(7, 5)
    if dow == 5:   # Fri, weights first 06:00
        return time(6, 0)
    return None  # No lifting on Wed/Sat/Sun

# Main lift mapping per weekday
MAIN_LIFT_BY_DOW = {
    1: BENCH_ID,   # Mon
    2: SQUAT_ID,   # Tue
    4: OHP_ID,     # Thu
    5: DEADLIFT_ID # Fri
}

# Periodisation percentages and prescriptions per week number
# Weeks: 1 volume, 2 strength-hybrid, 3 peak strength, 4 deload
WEEK_PCTS = {
    1: {"sets": 4, "reps": 8, "percent_1rm": 70.0, "rir_cue": 2.0},
    2: {"sets": 5, "reps": 5, "percent_1rm": 77.5, "rir_cue": 2.0},
    3: {"sets": 5, "reps": 3, "percent_1rm": 85.0, "rir_cue": 1.0},
    4: {"sets": 3, "reps": 5, "percent_1rm": 60.0, "rir_cue": 3.0},  # deload
}

# Assistance prescriptions
ASSISTANCE_1 = {"sets": 3, "reps_low": 10, "reps_high": 12, "rir_cue": 2.0}
ASSISTANCE_2 = {"sets": 3, "reps_low": 8,  "reps_high": 10, "rir_cue": 2.0}

# Core prescriptions (rep or time envelope, we store reps here)
CORE_SCHEME = {"sets": 3, "reps_low": 10, "reps_high": 15, "rir_cue": 2.0}
