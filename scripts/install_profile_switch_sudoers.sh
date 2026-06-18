#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="${SUDO_USER:-cleo}"
SUDOERS_FILE="/etc/sudoers.d/cleo-rover-profile-switch"
SCRIPT="$APP_DIR/scripts/set_rover_profile.sh"

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo scripts/install_profile_switch_sudoers.sh" >&2
  exit 1
fi

if [[ ! -x "$SCRIPT" ]]; then
  chmod +x "$SCRIPT"
fi

cat > "$SUDOERS_FILE" <<EOF
# Allow the Telegram agent user to switch Cleo Rover only between audited rover profiles.
$USER_NAME ALL=(root) NOPASSWD: $SCRIPT presence, $SCRIPT floor-cautious
EOF
chmod 440 "$SUDOERS_FILE"
visudo -cf "$SUDOERS_FILE"

echo "Installed sudoers rule for $USER_NAME to run $SCRIPT presence|floor-cautious without a password."
