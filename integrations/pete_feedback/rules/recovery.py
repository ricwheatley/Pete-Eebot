import random

def interpret(metrics: dict) -> str:
    sleep = metrics.get("sleep_hours")
    rhr = metrics.get("hr_resting")
    bits = []
    if sleep:
        bits.append(random.choice([
            f"slept {sleep:.1f}h 😴",
            f"{sleep:.1f} hours of shut-eye, recovery mode on",
            f"caught {sleep:.1f}h of Zzzs, decent reboot",
            f"rested {sleep:.1f}h — muscles whispered thanks",
        ]))
    if rhr:
        bits.append(random.choice([
            f"resting HR at {rhr:.0f} bpm ❤️",
            f"resting heart rate came in at {rhr:.0f}",
            f"{rhr:.0f} bpm at rest — cardiac gains",
            f"rest pulse {rhr:.0f} bpm, engine idling smooth",
        ]))
    return " | ".join(bits)