#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
SERVICE=/etc/systemd/system/cleo-rover.service

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo scripts/install_systemd.sh" >&2
  exit 1
fi

cat > "$SERVICE" <<EOF
[Unit]
Description=Cleo Rover Mk1 body service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$APP_DIR
Environment=CLEO_ROVER_MODE=sim
ExecStart=$APP_DIR/.venv/bin/uvicorn rover.service:app --host 0.0.0.0 --port 8099
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable cleo-rover.service

echo "Installed cleo-rover.service. Start with: sudo systemctl start cleo-rover"
echo "Logs: journalctl -u cleo-rover -f"
