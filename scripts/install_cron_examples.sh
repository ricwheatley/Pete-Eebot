#!/usr/bin/env bash
# Helper to print a ready-to-install cron schedule for Pete-Eebot.
#
# Usage:
#   ./scripts/install_cron_examples.sh | sudo tee /etc/cron.d/pete-eebot
#
# Environment variables:
#   PROJECT_DIR   - Root directory of the Pete-Eebot checkout (default: repo root)
#   PETE_BIN      - Path to the pete-e CLI binary (default: autodetected or ~/.local/bin/pete-e)
#   PYTHON_BIN    - Interpreter used for python -m scripts.weekly_calibration (default: python3)
#   PATH_PREFIX   - PATH line to prepend inside cron (default: includes pete-e directory + system paths)
#   LOG_FILE      - File that receives cron output (default: $PROJECT_DIR/logs/cron.log)
#   REBOOT_DELAY  - Seconds to sleep before the @reboot catch-up sync (default: 120)
#   CATCHUP_DAYS  - Days of history to sync on reboot (default: 3)
#   SYNC_DAYS     - Days of history to sync in the daily job (default: 1)
#   SYNC_RETRIES  - Retry count passed to pete-e sync (default: 3)
#   DAILY_MINUTE  - Minute for the daily sync+summary cron (default: 5)
#   DAILY_HOUR    - Hour for the daily sync+summary cron (default: 7)
#   WEEKLY_DAY    - Day-of-week for weekly calibration/plan (0-7, default: 1 for Monday)
#   WEEKLY_CAL_MINUTE - Minute for weekly calibration (default: 0)
#   WEEKLY_CAL_HOUR   - Hour for weekly calibration (default: 8)
#   WEEKLY_PLAN_MINUTE - Minute for weekly plan send (default: 5)
#   WEEKLY_PLAN_HOUR   - Hour for weekly plan send (default: 8)
#   LISTENER_LIMIT - Telegram poll limit passed to pete-e telegram (default: 5)
#   LISTENER_TIMEOUT - Telegram long poll timeout (default: 25)

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$PROJECT_ROOT}"

if command -v pete-e >/dev/null 2>&1; then
  DEFAULT_PETE_BIN="$(command -v pete-e)"
else
  DEFAULT_PETE_BIN="$HOME/.local/bin/pete-e"
fi
PETE_BIN="${PETE_BIN:-$DEFAULT_PETE_BIN}"

if command -v python3 >/dev/null 2>&1; then
  DEFAULT_PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  DEFAULT_PYTHON_BIN="$(command -v python)"
else
  DEFAULT_PYTHON_BIN="python3"
fi
PYTHON_BIN="${PYTHON_BIN:-$DEFAULT_PYTHON_BIN}"

LOG_FILE="${LOG_FILE:-$PROJECT_DIR/logs/cron.log}"
REBOOT_DELAY="${REBOOT_DELAY:-120}"
CATCHUP_DAYS="${CATCHUP_DAYS:-3}"
SYNC_DAYS="${SYNC_DAYS:-1}"
SYNC_RETRIES="${SYNC_RETRIES:-3}"
DAILY_MINUTE="${DAILY_MINUTE:-5}"
DAILY_HOUR="${DAILY_HOUR:-7}"
WEEKLY_DAY="${WEEKLY_DAY:-1}"
WEEKLY_CAL_MINUTE="${WEEKLY_CAL_MINUTE:-0}"
WEEKLY_CAL_HOUR="${WEEKLY_CAL_HOUR:-8}"
WEEKLY_PLAN_MINUTE="${WEEKLY_PLAN_MINUTE:-5}"
WEEKLY_PLAN_HOUR="${WEEKLY_PLAN_HOUR:-8}"
LISTENER_LIMIT="${LISTENER_LIMIT:-5}"
LISTENER_TIMEOUT="${LISTENER_TIMEOUT:-25}"

DEFAULT_PATH_PREFIX="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
if [[ "$PETE_BIN" == /* ]]; then
  PETE_DIR="$(dirname "$PETE_BIN")"
  case ":$DEFAULT_PATH_PREFIX:" in
    *":$PETE_DIR:"*) ;;
    *) DEFAULT_PATH_PREFIX="$PETE_DIR:$DEFAULT_PATH_PREFIX" ;;
  esac
fi
PATH_PREFIX="${PATH_PREFIX:-$DEFAULT_PATH_PREFIX}"

mkdir -p "$(dirname "$LOG_FILE")"

cat <<CRON_SNIPPET
SHELL=/bin/bash
PATH=$PATH_PREFIX
MAILTO=""

@reboot   sleep $REBOOT_DELAY && cd $PROJECT_DIR && $PETE_BIN sync --days $CATCHUP_DAYS --retries $SYNC_RETRIES >> $LOG_FILE 2>&1
$DAILY_MINUTE $DAILY_HOUR * * *  cd $PROJECT_DIR && $PETE_BIN sync --days $SYNC_DAYS --retries $SYNC_RETRIES && $PETE_BIN message --summary --send >> $LOG_FILE 2>&1
$WEEKLY_CAL_MINUTE $WEEKLY_CAL_HOUR * * $WEEKLY_DAY  cd $PROJECT_DIR && $PYTHON_BIN -m scripts.weekly_calibration >> $LOG_FILE 2>&1
$WEEKLY_PLAN_MINUTE $WEEKLY_PLAN_HOUR * * $WEEKLY_DAY  cd $PROJECT_DIR && $PETE_BIN message --plan --send >> $LOG_FILE 2>&1
* * * * *  cd $PROJECT_DIR && $PETE_BIN telegram --listen-once --limit $LISTENER_LIMIT --timeout $LISTENER_TIMEOUT >> $LOG_FILE 2>&1
CRON_SNIPPET

cat <<'CRON_HELP'

# Pipe this output into your crontab or /etc/cron.d/pete-eebot, for example:
#   ./scripts/install_cron_examples.sh | sudo tee /etc/cron.d/pete-eebot
# Override PETE_BIN, PYTHON_BIN, PROJECT_DIR, or LOG_FILE to match your environment.
CRON_HELP
