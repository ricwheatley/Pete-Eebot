#!/usr/bin/env bash
set -Eeuo pipefail

# Pete-Eebot deployment script.
#
# Expected production layout:
#   /opt/myapp/current          # active git checkout or release symlink
#   /opt/myapp/shared/.env
#   /opt/myapp/shared/venv/
#   /opt/myapp/scripts/deploy.sh
#   /var/log/pete_eebot/

PROJECT_ROOT="${PROJECT_ROOT:-/opt/myapp}"
APP_ROOT="${APP_ROOT:-${PROJECT_ROOT}/current}"
SHARED_ROOT="${SHARED_ROOT:-${PROJECT_ROOT}/shared}"
VENV_ROOT="${VENV_ROOT:-${SHARED_ROOT}/venv}"
ENV_FILE="${ENV_FILE:-${SHARED_ROOT}/.env}"
PYTHON_BIN="${PYTHON_BIN:-${VENV_ROOT}/bin/python3}"
SERVICE_NAME="${SERVICE_NAME:-peteeebot.service}"
LOGFILE="${LOGFILE:-/var/log/pete_eebot/deploy.log}"
SKIP_GIT_UPDATE="${SKIP_GIT_UPDATE:-0}"
export ENV_FILE PETEEEBOT_ENV_FILE="${PETEEEBOT_ENV_FILE:-${ENV_FILE}}"

mkdir -p "$(dirname "${LOGFILE}")"
if [[ "${DEPLOY_LOG_ATTACHED:-0}" != "1" ]]; then
    exec > >(tee -a "${LOGFILE}") 2>&1
fi

log() {
    printf '%s\n' "$*"
}

fail() {
    log "ERROR: $*"
    exit 1
}

notify_telegram() {
    local message="$1"
    local sender="${APP_ROOT}/scripts/send_telegram_message.py"

    if [[ -x "${PYTHON_BIN}" && -f "${sender}" ]]; then
        "${PYTHON_BIN}" "${sender}" "${message}" || log "WARNING: Telegram notification failed."
    else
        log "WARNING: Telegram notification skipped; sender or Python venv is unavailable."
    fi
}

restart_service() {
    local timeout_seconds="${SYSTEMCTL_RESTART_TIMEOUT_SECONDS:-60}"

    if command -v timeout >/dev/null 2>&1; then
        timeout "${timeout_seconds}s" sudo -n /bin/systemctl restart "${SERVICE_NAME}"
    else
        sudo -n /bin/systemctl restart "${SERVICE_NAME}"
    fi
}

on_error() {
    local exit_code=$?
    local line_no=${BASH_LINENO[0]:-unknown}

    log "ERROR: Deploy failed at line ${line_no} with exit code ${exit_code}."
    notify_telegram "Deploy failed on $(hostname): line ${line_no}, exit ${exit_code}."
    exit "${exit_code}"
}

trap on_error ERR

log "---- Deploy run at $(date -Is) ----"

[[ -d "${APP_ROOT}/.git" ]] || fail "Git repository not found at ${APP_ROOT}"
[[ -x "${PYTHON_BIN}" ]] || fail "Python venv not found at ${PYTHON_BIN}"
[[ -f "${VENV_ROOT}/bin/activate" ]] || fail "Virtual environment activation script not found at ${VENV_ROOT}/bin/activate"
[[ -f "${ENV_FILE}" ]] || fail ".env not found at ${ENV_FILE}"

set -a
# shellcheck source=/dev/null
source "${ENV_FILE}"
set +a

cd "${APP_ROOT}"
if [[ "${SKIP_GIT_UPDATE}" == "1" ]]; then
    log "Skipping git update because SKIP_GIT_UPDATE=1."
else
    log "Pulling latest code from ${APP_ROOT}..."
    git fetch --all --prune
    git reset --hard origin/main
    git clean -fdx
fi

COMMIT_INFO="$(git log -1 --pretty=format:'%s (%an)')"

log "Activating virtual environment..."
# shellcheck source=/dev/null
source "${VENV_ROOT}/bin/activate"

log "Installing application from ${APP_ROOT}..."
"${PYTHON_BIN}" -m pip install -e "${APP_ROOT}"

log "Writing and activating cron jobs..."
"${PYTHON_BIN}" -m pete_e.infrastructure.cron_manager --write --activate --summary

log "Sending Telegram notification before service restart..."
notify_telegram "Deploy installed on $(hostname): ${COMMIT_INFO}. Restarting ${SERVICE_NAME} now."

log "Restarting ${SERVICE_NAME}..."
restart_service

log "Deploy completed successfully at $(date -Is)"
