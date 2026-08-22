#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    printf '%s\n' "Run this installer as root." >&2
    exit 2
fi

readonly source_root="${1:-/opt/myapp/current/pete_e/resources}"

install -o root -g root -m 0644 "${source_root}/peteeebot.service" \
    /etc/systemd/system/peteeebot.service
install -o root -g root -m 0644 "${source_root}/peteeebot-deploy@.service" \
    /etc/systemd/system/peteeebot-deploy@.service
install -o root -g root -m 0755 "${source_root}/peteeebot-dispatch-deploy" \
    /usr/local/sbin/peteeebot-dispatch-deploy
visudo -cf "${source_root}/peteeebot-deploy.sudoers"
install -o root -g root -m 0440 "${source_root}/peteeebot-deploy.sudoers" \
    /etc/sudoers.d/peteeebot-deploy

/bin/systemctl daemon-reload
printf '%s\n' "Installed Pete-Eebot API and independent deployment-worker units."
printf '%s\n' "No service was started or restarted."
