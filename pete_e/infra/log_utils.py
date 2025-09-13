from datetime import datetime

from pete_e.config import settings


def log_message(msg: str, level: str = "INFO") -> None:
    """Append a timestamped message to the Pete history log."""
    log_file = settings.log_path
    log_file.parent.mkdir(parents=True, exist_ok=True)

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.utcnow().isoformat()}] [{level}] {msg}\n")
