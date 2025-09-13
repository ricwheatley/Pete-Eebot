from datetime import datetime

# Import the centralized settings
from pete_e.config import settings

# The hardcoded LOG_PATH has been removed.

def log_message(msg: str):
    """Append a timestamped message to the Pete history log."""
    # Use the LOG_PATH from the settings object
    log_file = settings.LOG_PATH
    log_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.utcnow().isoformat()}] {msg}\n")
