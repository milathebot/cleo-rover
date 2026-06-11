#!/usr/bin/env bash
set -euo pipefail

# Cleo Rover Mk1 Pi setup helper.
# Run on the Raspberry Pi after copying/cloning this repo.

if [[ $EUID -eq 0 ]]; then
  echo "Run as the pi/user account, not root." >&2
  exit 1
fi

sudo apt-get update
sudo apt-get install -y \
  python3-venv python3-pip python3-pil \
  git curl i2c-tools python3-libcamera \
  portaudio19-dev alsa-utils

python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e .[pi]

cat <<'MSG'

Pi package setup complete.

Manual Pi config to check with `sudo raspi-config`:
  - Interface Options -> SPI -> enable
  - Interface Options -> I2C -> enable if Freenove/sensors need it
  - Interface Options -> Camera -> enable, if present on your OS image
  - System Options -> Wireless LAN -> configured

Then install service:
  sudo scripts/install_systemd.sh

MSG
