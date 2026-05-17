#!/usr/bin/env bash
set -Eeuo pipefail

# Stable webhook entrypoint kept outside the Git checkout.
# Copy this file to /opt/myapp/scripts/deploy.sh.

PROJECT_ROOT="${PROJECT_ROOT:-/opt/myapp}"
APP_ROOT="${APP_ROOT:-${PROJECT_ROOT}/current}"
SHARED_ROOT="${SHARED_ROOT:-${PROJECT_ROOT}/shared}"
VENV_ROOT="${VENV_ROOT:-${SHARED_ROOT}/venv}"
ENV_FILE="${ENV_FILE:-${SHARED_ROOT}/.env}"
LOGFILE="${LOGFILE:-/var/log/pete_eebot/deploy.log}"
LOCKFILE="${LOCKFILE:-/var/lock/pete_eebot-deploy.lock}"
TRACKED_DEPLOY="${TRACKED_DEPLOY:-${APP_ROOT}/pete_e/resources/deploy.sh}"
export ENV_FILE PETEEEBOT_ENV_FILE="${PETEEEBOT_ENV_FILE:-${ENV_FILE}}"

mkdir -p "$(dirname "${LOGFILE}")"
exec > >(tee -a "${LOGFILE}") 2>&1

printf '%s\n' "---- Deploy wrapper run at $(date -Is) ----"
printf '%s\n' "Webhook metadata: delivery=${WEBHOOK_DELIVERY_ID:-unknown} sha=${GITHUB_COMMIT_SHA:-unknown} ref=${GITHUB_REF:-unknown}"
mkdir -p "$(dirname "${LOCKFILE}")"

exec 9>"${LOCKFILE}"
if ! flock -n 9; then
    printf '%s\n' "Deploy already in progress; ignoring duplicate trigger. lock=${LOCKFILE} pid=$$ delivery=${WEBHOOK_DELIVERY_ID:-unknown} sha=${GITHUB_COMMIT_SHA:-unknown}"
    exit 0
fi
printf '%s\n' "Deploy lock acquired. lock=${LOCKFILE} pid=$$"

if [[ ! -d "${APP_ROOT}/.git" ]]; then
    printf '%s\n' "ERROR: Git repository not found at ${APP_ROOT}"
    exit 1
fi

cd "${APP_ROOT}"
printf '%s\n' "Pulling latest code from ${APP_ROOT}..."
git fetch --all --prune
git reset --hard origin/main
git clean -fdx

if [[ ! -f "${TRACKED_DEPLOY}" ]]; then
    printf '%s\n' "ERROR: Tracked deploy script not found at ${TRACKED_DEPLOY}"
    exit 1
fi

exec env \
    PROJECT_ROOT="${PROJECT_ROOT}" \
    APP_ROOT="${APP_ROOT}" \
    SHARED_ROOT="${SHARED_ROOT}" \
    VENV_ROOT="${VENV_ROOT}" \
    ENV_FILE="${ENV_FILE}" \
    PETEEEBOT_ENV_FILE="${PETEEEBOT_ENV_FILE}" \
    LOGFILE="${LOGFILE}" \
    LOCKFILE="${LOCKFILE}" \
    WEBHOOK_DELIVERY_ID="${WEBHOOK_DELIVERY_ID:-}" \
    GITHUB_EVENT_NAME="${GITHUB_EVENT_NAME:-}" \
    GITHUB_COMMIT_SHA="${GITHUB_COMMIT_SHA:-}" \
    GITHUB_REF="${GITHUB_REF:-}" \
    DEPLOY_LOG_ATTACHED=1 \
    SKIP_GIT_UPDATE=1 \
    bash "${TRACKED_DEPLOY}"
