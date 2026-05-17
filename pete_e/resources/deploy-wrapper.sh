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
TRACKED_DEPLOY="${TRACKED_DEPLOY:-${APP_ROOT}/pete_e/resources/deploy.sh}"
export ENV_FILE PETEEEBOT_ENV_FILE="${PETEEEBOT_ENV_FILE:-${ENV_FILE}}"

mkdir -p "$(dirname "${LOGFILE}")"
exec > >(tee -a "${LOGFILE}") 2>&1

printf '%s\n' "---- Deploy wrapper run at $(date -Is) ----"

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
    DEPLOY_LOG_ATTACHED=1 \
    SKIP_GIT_UPDATE=1 \
    bash "${TRACKED_DEPLOY}"
