#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root, usually via sudo." >&2
  exit 1
fi

PROFILE="${1:-}"
APP_DIR="/home/cleo/cleo-rover"
SERVICE="cleo-rover.service"
OVERRIDE_DIR="/etc/systemd/system/${SERVICE}.d"
OVERRIDE_FILE="${OVERRIDE_DIR}/override.conf"

case "$PROFILE" in
  presence|safe|no-motors)
    CONFIG_PATH="${APP_DIR}/config/rover.hardware.presence.json"
    PROFILE_NAME="hardware-presence-no-motors"
    ;;
  floor-cautious|floor)
    CONFIG_PATH="${APP_DIR}/config/rover.hardware.floor.cautious.json"
    PROFILE_NAME="hardware-floor-cautious"
    ;;
  *)
    echo "Usage: sudo scripts/set_rover_profile.sh presence|floor-cautious" >&2
    exit 2
    ;;
esac

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "Missing config: $CONFIG_PATH" >&2
  exit 3
fi

mkdir -p "$OVERRIDE_DIR"
cat > "$OVERRIDE_FILE" <<EOF
[Service]
Environment=
Environment=CLEO_ROVER_MODE=hardware
Environment=CLEO_ROVER_CONFIG=$CONFIG_PATH
EOF

systemctl daemon-reload
systemctl restart "$SERVICE"
sleep 2
systemctl is-active --quiet "$SERVICE"
echo "cleo-rover switched to $PROFILE_NAME ($CONFIG_PATH)"
