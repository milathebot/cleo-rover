#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
SERVICE=/etc/systemd/system/cleo-rover-telegram-agent.service
ENV_FILE=/etc/cleo-rover/telegram-agent.env

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo scripts/install_telegram_agent_systemd.sh" >&2
  exit 1
fi

mkdir -p /etc/cleo-rover
if [[ ! -f "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<'EOF'
# Create a bot with @BotFather, then set the token here.
CLEO_ROVER_TELEGRAM_TOKEN=
# Your Telegram numeric user id. Get it from @userinfobot.
CLEO_ROVER_TELEGRAM_ALLOWED_USER_ID=
CLEO_ROVER_WORKDIR=/home/cleo/cleo-rover
EOF
  chmod 600 "$ENV_FILE"
  chown root:root "$ENV_FILE"
fi

cat > "$SERVICE" <<EOF
[Unit]
Description=Cleo Rover Telegram command agent
After=network-online.target cleo-rover-body.service
Wants=network-online.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$APP_DIR/.venv/bin/cleo-rover-telegram-agent
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable cleo-rover-telegram-agent.service

echo "Installed cleo-rover-telegram-agent.service."
echo "Edit credentials: sudo nano $ENV_FILE"
echo "Optional floor profile switching helper: sudo scripts/install_profile_switch_sudoers.sh"
echo "Start: sudo systemctl start cleo-rover-telegram-agent"
echo "Logs: journalctl -u cleo-rover-telegram-agent -f"
