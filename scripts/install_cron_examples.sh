#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -n "${PYTHON_BIN:-}" ]]; then
    CANDIDATE_PYTHON_BINS=("${PYTHON_BIN}")
else
    CANDIDATE_PYTHON_BINS=(
        "${PROJECT_ROOT}/venv/bin/python3"
        "${PROJECT_ROOT}/.venv/bin/python3"
        "${FALLBACK_PYTHON_BIN:-python3}"
    )
fi

PYTHON_BIN="${CANDIDATE_PYTHON_BINS[0]}"
for candidate in "${CANDIDATE_PYTHON_BINS[@]}"; do
    if [[ "${candidate}" == "python3" ]] || [[ -x "${candidate}" ]]; then
        PYTHON_BIN="${candidate}"
        break
    fi
done

cd "${PROJECT_ROOT}"

if [[ $# -eq 0 ]]; then
    set -- --write --activate --summary
fi

exec "${PYTHON_BIN}" -m pete_e.infrastructure.cron_manager "$@"
