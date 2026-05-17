#!/usr/bin/env bash
# Weekly backup script for Pete-Eebot Postgres data and local secret files.
set -Eeuo pipefail

umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="${APP_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"

if [[ -z "${PROJECT_ROOT:-}" ]]; then
    if [[ "$(basename "${APP_ROOT}")" == "app" || "$(basename "${APP_ROOT}")" == "current" ]]; then
        PROJECT_ROOT="$(cd "${APP_ROOT}/.." && pwd)"
    else
        PROJECT_ROOT="${APP_ROOT}"
    fi
fi

if [[ -z "${ENV_FILE:-}" ]]; then
    if [[ -f "${PROJECT_ROOT}/shared/.env" ]]; then
        ENV_FILE="${PROJECT_ROOT}/shared/.env"
    else
        ENV_FILE="${PROJECT_ROOT}/.env"
    fi
fi

if [[ ! -f "${ENV_FILE}" ]]; then
    printf 'ERROR: Environment file not found at %s.\n' "${ENV_FILE}" >&2
    exit 1
fi

# Preserve explicit command-line environment overrides when loading .env.
declare -A ENV_OVERRIDES=()
ENV_OVERRIDE_NAMES=(
    VENV_ROOT
    PYTHON_BIN
    BACKUP_ROOT
    DB_BACKUP_DIR
    SECRETS_BACKUP_DIR
    CLOUD_STAGING_DIR
    LOG_DIR
    LOG_FILE
    RETENTION_WEEKS
    TOKENS_FILE
    WITHINGS_TOKEN_FILE
    BACKUP_CLOUD_UPLOAD
    DROPBOX_BACKUP_DIR
    DROPBOX_BACKUP_TIMEOUT
    BACKUP_ENCRYPTION_KEY_FILE
    BACKUP_ENCRYPTION_PASSPHRASE
)

for name in "${ENV_OVERRIDE_NAMES[@]}"; do
    if [[ -v "${name}" ]]; then
        ENV_OVERRIDES["${name}"]="${!name}"
    fi
done

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

for name in "${!ENV_OVERRIDES[@]}"; do
    printf -v "${name}" '%s' "${ENV_OVERRIDES[${name}]}"
    export "${name}"
done

if [[ -z "${VENV_ROOT:-}" ]]; then
    if [[ -d "${PROJECT_ROOT}/shared/venv" ]]; then
        VENV_ROOT="${PROJECT_ROOT}/shared/venv"
    else
        VENV_ROOT="${PROJECT_ROOT}/venv"
    fi
fi
PYTHON_BIN="${PYTHON_BIN:-${VENV_ROOT}/bin/python3}"

BACKUP_ROOT="${BACKUP_ROOT:-${PROJECT_ROOT}/backups}"
DB_BACKUP_DIR="${DB_BACKUP_DIR:-${BACKUP_ROOT}/postgres}"
SECRETS_BACKUP_DIR="${SECRETS_BACKUP_DIR:-${BACKUP_ROOT}/secrets}"
CLOUD_STAGING_DIR="${CLOUD_STAGING_DIR:-${BACKUP_ROOT}/cloud-staging}"
LOG_DIR="${LOG_DIR:-${PROJECT_ROOT}/logs}"
LOG_FILE="${LOG_FILE:-${LOG_DIR}/backup_db.log}"
RETENTION_WEEKS="${RETENTION_WEEKS:-8}"

TOKENS_FILE="${TOKENS_FILE:-${WITHINGS_TOKEN_FILE:-${HOME}/.config/pete_eebot/.withings_tokens.json}}"

BACKUP_CLOUD_UPLOAD="${BACKUP_CLOUD_UPLOAD:-0}"
DROPBOX_BACKUP_DIR="${DROPBOX_BACKUP_DIR:-/Pete-Eebot Backups}"
DROPBOX_BACKUP_DIR="${DROPBOX_BACKUP_DIR%/}"

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

if ! command -v pg_dump >/dev/null 2>&1; then
    log "ERROR: pg_dump is not available on PATH."
    exit 1
fi

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
SECRET_BACKUP_FILES=()

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
    SECRET_BACKUP_FILES+=("${dest_file}")
    log "${label} copied to ${dest_file}."
}

copy_secret "${ENV_FILE}" "${SECRETS_BACKUP_DIR}" ".env"
copy_secret "${TOKENS_FILE}" "${SECRETS_BACKUP_DIR}" ".withings_tokens.json"

prune_old_files() {
    local dir=$1
    local pattern=$2

    if [[ ! -d "${dir}" ]]; then
        return 0
    fi

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

encrypt_for_cloud() {
    local source_file=$1
    local label=$2
    local output_file="${CLOUD_STAGING_DIR}/${label}_${TIMESTAMP}.enc"

    if [[ -n "${BACKUP_ENCRYPTION_KEY_FILE:-}" ]]; then
        if [[ ! -f "${BACKUP_ENCRYPTION_KEY_FILE}" ]]; then
            log "ERROR: BACKUP_ENCRYPTION_KEY_FILE does not exist: ${BACKUP_ENCRYPTION_KEY_FILE}"
            return 1
        fi
        openssl enc -aes-256-cbc -pbkdf2 -salt \
            -in "${source_file}" \
            -out "${output_file}" \
            -pass "file:${BACKUP_ENCRYPTION_KEY_FILE}"
    elif [[ -n "${BACKUP_ENCRYPTION_PASSPHRASE:-}" ]]; then
        openssl enc -aes-256-cbc -pbkdf2 -salt \
            -in "${source_file}" \
            -out "${output_file}" \
            -pass env:BACKUP_ENCRYPTION_PASSPHRASE
    else
        log "ERROR: BACKUP_CLOUD_UPLOAD=1 requires BACKUP_ENCRYPTION_KEY_FILE or BACKUP_ENCRYPTION_PASSPHRASE."
        return 1
    fi

    chmod 600 "${output_file}"
    CLOUD_UPLOAD_FILES+=("${output_file}")
    log "Encrypted ${source_file} for cloud upload at ${output_file}."
}

if [[ "${BACKUP_CLOUD_UPLOAD}" == "1" ]]; then
    if ! command -v openssl >/dev/null 2>&1; then
        log "ERROR: openssl is required for encrypted cloud backups."
        exit 1
    fi
    if [[ ! -x "${PYTHON_BIN}" ]]; then
        log "ERROR: Python venv not found at ${PYTHON_BIN}."
        exit 1
    fi

    mkdir -p "${CLOUD_STAGING_DIR}"
    chmod 700 "${CLOUD_STAGING_DIR}"
    CLOUD_UPLOAD_FILES=()

    encrypt_for_cloud "${DB_BACKUP_FILE}" "postgres"
    for secret_file in "${SECRET_BACKUP_FILES[@]}"; do
        case "$(basename "${secret_file}")" in
            .env.*) encrypt_for_cloud "${secret_file}" "env" ;;
            .withings_tokens.json.*) encrypt_for_cloud "${secret_file}" "withings_tokens" ;;
            *) encrypt_for_cloud "${secret_file}" "secret" ;;
        esac
    done

    log "Uploading encrypted backup artifacts to Dropbox at ${DROPBOX_BACKUP_DIR}."
    "${PYTHON_BIN}" "${APP_ROOT}/scripts/upload_backup_to_dropbox.py" \
        --target-dir "${DROPBOX_BACKUP_DIR}/${TIMESTAMP}" \
        --latest-dir "${DROPBOX_BACKUP_DIR}/latest" \
        "${CLOUD_UPLOAD_FILES[@]}"
    log "Dropbox backup upload completed."
fi

prune_old_files "${DB_BACKUP_DIR}" 'pete_eebot_*.dump'
prune_old_files "${SECRETS_BACKUP_DIR}" '.env.*'
prune_old_files "${SECRETS_BACKUP_DIR}" '.withings_tokens.json.*'
prune_old_files "${CLOUD_STAGING_DIR}" '*.enc'

log "Backup routine completed successfully."
