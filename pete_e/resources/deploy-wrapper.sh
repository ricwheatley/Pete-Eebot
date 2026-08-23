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
DEPLOY_GIT_REMOTE="${PETEEEBOT_DEPLOY_GIT_REMOTE:-origin}"
EXPECTED_REMOTE_URL="${PETEEEBOT_DEPLOY_GIT_REMOTE_URL:-}"
DEPLOY_REF="${PETEEEBOT_GITHUB_DEPLOY_REF:-refs/heads/main}"
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

if [[ ! "${DEPLOY_GIT_REMOTE}" =~ ^[A-Za-z0-9._-]+$ ]]; then
    printf '%s\n' "ERROR: PETEEEBOT_DEPLOY_GIT_REMOTE is invalid."
    exit 1
fi
if [[ -z "${EXPECTED_REMOTE_URL}" ]]; then
    printf '%s\n' "ERROR: PETEEEBOT_DEPLOY_GIT_REMOTE_URL is not configured."
    exit 1
fi
if [[ "${GITHUB_EVENT_NAME:-}" != "push" || "${GITHUB_REF:-}" != "${DEPLOY_REF}" || "${DEPLOY_REF}" != "refs/heads/main" ]]; then
    printf '%s\n' "ERROR: Deployment metadata is not an allowed main-branch push."
    exit 1
fi
if [[ ! "${GITHUB_COMMIT_SHA:-}" =~ ^[0-9a-f]{40}$ || "${GITHUB_COMMIT_SHA}" == "0000000000000000000000000000000000000000" ]]; then
    printf '%s\n' "ERROR: GITHUB_COMMIT_SHA is not a valid deployable commit SHA."
    exit 1
fi

cd "${APP_ROOT}"
ACTUAL_REMOTE_URL="$(git remote get-url "${DEPLOY_GIT_REMOTE}")"
if [[ "${ACTUAL_REMOTE_URL}" != "${EXPECTED_REMOTE_URL}" ]]; then
    printf '%s\n' "ERROR: Configured Git remote URL does not match ${DEPLOY_GIT_REMOTE}."
    exit 1
fi
REMOTE_TRACKING_REF="refs/remotes/${DEPLOY_GIT_REMOTE}/main"
printf '%s\n' "Fetching the allowed main ref from ${DEPLOY_GIT_REMOTE}..."
git fetch --prune "${DEPLOY_GIT_REMOTE}" "+${DEPLOY_REF}:${REMOTE_TRACKING_REF}"
if ! git cat-file -e "${GITHUB_COMMIT_SHA}^{commit}"; then
    printf '%s\n' "ERROR: Signed commit does not exist in the expected repository."
    exit 1
fi
if ! git merge-base --is-ancestor "${GITHUB_COMMIT_SHA}" "${REMOTE_TRACKING_REF}"; then
    printf '%s\n' "ERROR: Signed commit is not an ancestor of the fetched main ref."
    exit 1
fi
printf '%s\n' "Selecting signed commit ${GITHUB_COMMIT_SHA}..."
git reset --hard "${GITHUB_COMMIT_SHA}"
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
    PETEEEBOT_DEPLOY_GIT_REMOTE="${DEPLOY_GIT_REMOTE}" \
    PETEEEBOT_DEPLOY_GIT_REMOTE_URL="${EXPECTED_REMOTE_URL}" \
    PETEEEBOT_GITHUB_DEPLOY_REF="${DEPLOY_REF}" \
    DEPLOY_LOG_ATTACHED=1 \
    SKIP_GIT_UPDATE=1 \
    bash "${TRACKED_DEPLOY}"
