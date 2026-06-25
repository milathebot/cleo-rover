#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
UNIT=cleo-rover-body.service
SERVICE=/etc/systemd/system/$UNIT

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo scripts/install_systemd.sh" >&2
  exit 1
fi

# Safe default: hardware mode with the no-motor presence config. Per-robot tuning
# (CLEO_ROVER_CONFIG=...rover.hardware.local.json) and mind creds (HERMES_* /
# CLEO_ROVER_HERMES_*) belong in a drop-in (`sudo systemctl edit $UNIT`) so that
# re-running this installer never clobbers them.
cat > "$SERVICE" <<EOF
[Unit]
Description=Cleo Rover Mk1 body service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$APP_DIR
Environment=CLEO_ROVER_MODE=hardware
Environment=CLEO_ROVER_CONFIG=$APP_DIR/config/rover.hardware.presence.json
# To connect a mind, drop-in: Environment=CLEO_ROVER_HERMES_API_BASE=http://host:port/v1
# Bind 0.0.0.0 instead of 127.0.0.1 only if the mind connects over the LAN.
ExecStart=$APP_DIR/.venv/bin/uvicorn rover.service:app --host 127.0.0.1 --port 8099
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$UNIT"

echo "Installed $UNIT. Start with: sudo systemctl start cleo-rover-body"
echo "Per-robot config/creds: sudo systemctl edit cleo-rover-body  (drop-in, survives reinstall)"
echo "Logs: journalctl -u cleo-rover-body -f"
