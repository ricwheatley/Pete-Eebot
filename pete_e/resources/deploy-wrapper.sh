#!/usr/bin/env bash
set -Eeuo pipefail

# Stable webhook entrypoint kept outside the Git checkout.
# Copy this file to /home/ricwheatley/pete-eebot/deploy.sh.

PROJECT_ROOT="${PROJECT_ROOT:-/home/ricwheatley/pete-eebot}"
APP_ROOT="${APP_ROOT:-${PROJECT_ROOT}/app}"
VENV_ROOT="${VENV_ROOT:-${PROJECT_ROOT}/venv}"
LOGFILE="${LOGFILE:-${PROJECT_ROOT}/deploy.log}"
TRACKED_DEPLOY="${TRACKED_DEPLOY:-${APP_ROOT}/pete_e/resources/deploy.sh}"

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
    VENV_ROOT="${VENV_ROOT}" \
    LOGFILE="${LOGFILE}" \
    SKIP_GIT_UPDATE=1 \
    bash "${TRACKED_DEPLOY}"
