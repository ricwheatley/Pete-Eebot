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
UV_BIN="${UV_BIN:-${SHARED_ROOT}/uv-tool/bin/uv}"
EXPECTED_UV_VERSION="${EXPECTED_UV_VERSION:-0.12.5}"
SERVICE_NAME="${SERVICE_NAME:-peteeebot.service}"
LOGFILE="${LOGFILE:-/var/log/pete_eebot/deploy.log}"
LOCKFILE="${LOCKFILE:-/var/lock/pete_eebot-deploy.lock}"
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

DEPLOY_PID="$$"
DEPLOY_START_AT="$(date -Is)"
log "---- Deploy run at ${DEPLOY_START_AT} ----"
log "Deploy metadata: pid=${DEPLOY_PID} delivery=${WEBHOOK_DELIVERY_ID:-unknown} sha=${GITHUB_COMMIT_SHA:-unknown} event=${GITHUB_EVENT_NAME:-unknown} ref=${GITHUB_REF:-unknown}"
mkdir -p "$(dirname "${LOCKFILE}")"
exec 9>"${LOCKFILE}"
if ! flock -n 9; then
    log "Deploy already in progress; ignoring duplicate trigger. lock=${LOCKFILE} pid=${DEPLOY_PID} delivery=${WEBHOOK_DELIVERY_ID:-unknown} sha=${GITHUB_COMMIT_SHA:-unknown}"
    exit 0
fi
log "Deploy lock acquired. lock=${LOCKFILE} pid=${DEPLOY_PID}"

[[ -d "${APP_ROOT}/.git" ]] || fail "Git repository not found at ${APP_ROOT}"
[[ -x "${PYTHON_BIN}" ]] || fail "Python venv not found at ${PYTHON_BIN}"
[[ -x "${UV_BIN}" ]] || fail "Pinned uv executable not found at ${UV_BIN}"
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
[[ -f "${APP_ROOT}/pyproject.toml" ]] || fail "Dependency input not found at ${APP_ROOT}/pyproject.toml"
[[ -f "${APP_ROOT}/uv.lock" ]] || fail "Dependency lock not found at ${APP_ROOT}/uv.lock"

ACTUAL_UV_VERSION="$("${UV_BIN}" --version | awk '{print $2}')"
[[ "${ACTUAL_UV_VERSION}" == "${EXPECTED_UV_VERSION}" ]] || fail "uv ${EXPECTED_UV_VERSION} required; found ${ACTUAL_UV_VERSION}"

log "Activating virtual environment..."
# shellcheck source=/dev/null
source "${VENV_ROOT}/bin/activate"

log "Installing the frozen runtime graph and non-editable application from ${APP_ROOT}..."
"${UV_BIN}" lock --project "${APP_ROOT}" --check
UV_PROJECT_ENVIRONMENT="${VENV_ROOT}" "${UV_BIN}" sync \
    --project "${APP_ROOT}" \
    --frozen \
    --no-dev \
    --no-editable

log "Checking installed dependency consistency..."
"${UV_BIN}" pip check --python "${PYTHON_BIN}"

log "Running read-only schema upgrade preflight..."
"${PYTHON_BIN}" -m pete_e.cli.schema preflight

if [[ "${SCHEMA_BACKUP_BEFORE_UPGRADE:-1}" == "1" ]]; then
    BACKUP_SCRIPT="${APP_ROOT}/scripts/backup_db.sh"
    [[ -x "${BACKUP_SCRIPT}" ]] || fail "Database backup script is unavailable or not executable."
    log "Backing up PostgreSQL before schema upgrade..."
    PROJECT_ROOT="${PROJECT_ROOT}" APP_ROOT="${APP_ROOT}" ENV_FILE="${ENV_FILE}" \
        "${BACKUP_SCRIPT}"
else
    log "WARNING: Pre-migration backup explicitly disabled with SCHEMA_BACKUP_BEFORE_UPGRADE=0."
fi

log "Applying authoritative database migrations..."
"${PYTHON_BIN}" -m pete_e.cli.schema upgrade

log "Verifying the application role can read the required schema revision..."
"${PYTHON_BIN}" -m pete_e.cli.schema verify

log "Writing and activating cron jobs..."
"${PYTHON_BIN}" -m pete_e.infrastructure.cron_manager --write --activate --summary

log "Sending Telegram notification before service restart..."
notify_telegram "Deploy installed on $(hostname): ${COMMIT_INFO}. Restarting ${SERVICE_NAME} now."

log "Restarting ${SERVICE_NAME}..."
restart_service

DEPLOY_END_AT="$(date -Is)"
log "Deploy completed successfully at ${DEPLOY_END_AT} (pid=${DEPLOY_PID}, delivery=${WEBHOOK_DELIVERY_ID:-unknown}, sha=${GITHUB_COMMIT_SHA:-unknown})"
