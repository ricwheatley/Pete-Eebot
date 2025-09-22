#!/usr/bin/env bash
# Weekly backup script for Pete Eebot Postgres database and secret files.
set -euo pipefail

umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

BACKUP_ROOT="${BACKUP_ROOT:-${PROJECT_ROOT}/backups}"
DB_BACKUP_DIR="${DB_BACKUP_DIR:-${BACKUP_ROOT}/postgres}"
SECRETS_BACKUP_DIR="${SECRETS_BACKUP_DIR:-${BACKUP_ROOT}/secrets}"
LOG_DIR="${LOG_DIR:-${PROJECT_ROOT}/logs}"
LOG_FILE="${LOG_FILE:-${LOG_DIR}/backup_db.log}"
RETENTION_WEEKS="${RETENTION_WEEKS:-8}"

ENV_FILE="${ENV_FILE:-${PROJECT_ROOT}/.env}"
TOKENS_FILE="${TOKENS_FILE:-${PROJECT_ROOT}/.withings_tokens.json}"

mkdir -p "${DB_BACKUP_DIR}" "${SECRETS_BACKUP_DIR}" "${LOG_DIR}"
chmod 700 "${BACKUP_ROOT}" "${DB_BACKUP_DIR}" "${SECRETS_BACKUP_DIR}"
touch "${LOG_FILE}"
chmod 600 "${LOG_FILE}"

log() {
    local timestamp
    timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    printf '%s %s\n' "${timestamp}" "$*" | tee -a "${LOG_FILE}"
}

on_error() {
    local exit_code=$1
    local line_no=$2
    log "ERROR: Backup failed at line ${line_no} (exit code ${exit_code})."
}

trap 'on_error $? $LINENO' ERR

log "Starting backup routine using BACKUP_ROOT=${BACKUP_ROOT}."

if [[ ! -f "${ENV_FILE}" ]]; then
    log "ERROR: Environment file not found at ${ENV_FILE}."
    exit 1
fi

if ! command -v pg_dump >/dev/null 2>&1; then
    log "ERROR: pg_dump is not available on PATH."
    exit 1
fi

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

DATABASE_URL="${DATABASE_URL:-}"
POSTGRES_USER="${POSTGRES_USER:-}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}"
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-}"

if [[ -z "${DATABASE_URL}" && ( -z "${POSTGRES_USER}" || -z "${POSTGRES_PASSWORD}" || -z "${POSTGRES_DB}" ) ]]; then
    log "ERROR: Database connection details are incomplete. Set DATABASE_URL or the POSTGRES_* variables in ${ENV_FILE}."
    exit 1
fi

TIMESTAMP="$(date -u +"%Y%m%dT%H%M%SZ")"
DB_BACKUP_FILE="${DB_BACKUP_DIR}/pete_eebot_${TIMESTAMP}.dump"

if [[ -n "${POSTGRES_USER}" && -n "${POSTGRES_PASSWORD}" && -n "${POSTGRES_DB}" ]]; then
    export PGPASSWORD="${POSTGRES_PASSWORD}"
    pg_dump --host "${POSTGRES_HOST}" \
            --port "${POSTGRES_PORT}" \
            --username "${POSTGRES_USER}" \
            --format=custom \
            --file "${DB_BACKUP_FILE}" \
            "${POSTGRES_DB}"
    unset PGPASSWORD
else
    pg_dump --format=custom --file "${DB_BACKUP_FILE}" "${DATABASE_URL}"
fi

chmod 600 "${DB_BACKUP_FILE}"
ln -sf "$(basename "${DB_BACKUP_FILE}")" "${DB_BACKUP_DIR}/latest.dump"
log "Database backup created at ${DB_BACKUP_FILE}."

copy_secret() {
    local source_file=$1
    local target_dir=$2
    local label=$3

    if [[ ! -f "${source_file}" ]]; then
        log "WARN: ${label} not found at ${source_file}, skipping."
        return 0
    fi

    local dest_file="${target_dir}/$(basename "${source_file}").${TIMESTAMP}"
    cp "${source_file}" "${dest_file}"
    chmod 600 "${dest_file}"
    ln -sf "$(basename "${dest_file}")" "${target_dir}/$(basename "${source_file}").latest"
    log "${label} copied to ${dest_file}."
}

copy_secret "${ENV_FILE}" "${SECRETS_BACKUP_DIR}" ".env"
copy_secret "${TOKENS_FILE}" "${SECRETS_BACKUP_DIR}" ".withings_tokens.json"

prune_old_files() {
    local dir=$1
    local pattern=$2

    if [[ ${RETENTION_WEEKS} -le 0 ]]; then
        return 0
    fi

    local retention_days=$(( RETENTION_WEEKS * 7 ))

    while IFS= read -r file; do
        [[ -z "${file}" ]] && continue
        log "Pruning old backup ${file}."
        rm -f "${file}"
    done < <(find "${dir}" -type f -name "${pattern}" -mtime +"${retention_days}")
}

prune_old_files "${DB_BACKUP_DIR}" 'pete_eebot_*.dump'
prune_old_files "${SECRETS_BACKUP_DIR}" '.env.*'
prune_old_files "${SECRETS_BACKUP_DIR}" '.withings_tokens.json.*'

log "Backup routine completed successfully."
