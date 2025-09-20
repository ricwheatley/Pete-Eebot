# (Functional) Git helper – stages all changes and commits with a standardized message (used in automation to commit new data)

import subprocess
from datetime import datetime

def commit_changes(report_type: str, phrase: str):
    """Stage all changes and commit to git."""
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
    subprocess.run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"], check=True)
    subprocess.run(["git", "add", "-A"], check=False)
    msg = f"pete log update ({report_type}) | {phrase} ({datetime.utcnow().strftime('%Y-%m-%d')})"
    try:
        subprocess.run(["git", "commit", "-m", msg], check=True)
        subprocess.run(["git", "push"], check=True)
    except subprocess.CalledProcessError:
        print("No changes to commit.")
