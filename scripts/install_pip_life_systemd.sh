#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
SERVICE=/etc/systemd/system/cleo-rover-pip-life.service
INTERVAL="${CLEO_ROVER_PIP_LIFE_INTERVAL:-300}"
ALLOW_MOVEMENT="${CLEO_ROVER_PIP_LIFE_ALLOW_MOVEMENT:-0}"
EXTRA_ARGS=""

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo scripts/install_pip_life_systemd.sh" >&2
  exit 1
fi

if [[ "$ALLOW_MOVEMENT" == "1" || "$ALLOW_MOVEMENT" == "true" ]]; then
  EXTRA_ARGS="--allow-movement"
fi

cat > "$SERVICE" <<EOF
[Unit]
Description=Pip office-life loop (observation-first)
After=network-online.target cleo-rover.service
Wants=network-online.target
Requires=cleo-rover.service

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/cleo-rover-pip-life --interval $INTERVAL $EXTRA_ARGS
Restart=on-failure
RestartSec=8

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable cleo-rover-pip-life.service

echo "Installed cleo-rover-pip-life.service. Start with: sudo systemctl start cleo-rover-pip-life"
echo "Default is observation-only. To install with movement allowed later: CLEO_ROVER_PIP_LIFE_ALLOW_MOVEMENT=1 sudo scripts/install_pip_life_systemd.sh"
echo "Logs: journalctl -u cleo-rover-pip-life -f"
