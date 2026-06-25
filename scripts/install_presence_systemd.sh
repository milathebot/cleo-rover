#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
SERVICE=/etc/systemd/system/cleo-rover-presence.service
INTERVAL="${CLEO_ROVER_PRESENCE_INTERVAL:-8}"
SNAPSHOT_EVERY="${CLEO_ROVER_PRESENCE_SNAPSHOT_EVERY:-0}"
GLANCE_EVERY="${CLEO_ROVER_PRESENCE_GLANCE_EVERY:-3}"

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo scripts/install_presence_systemd.sh" >&2
  exit 1
fi

cat > "$SERVICE" <<EOF
[Unit]
Description=Cleo Rover non-driving presence loop
After=network-online.target cleo-rover-body.service
Wants=network-online.target
Requires=cleo-rover-body.service

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/cleo-rover-presence --interval $INTERVAL --snapshot-every $SNAPSHOT_EVERY --glance-every $GLANCE_EVERY
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable cleo-rover-presence.service

echo "Installed cleo-rover-presence.service. Start with: sudo systemctl start cleo-rover-presence"
echo "Logs: journalctl -u cleo-rover-presence -f"
