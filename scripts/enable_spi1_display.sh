#!/usr/bin/env bash
set -euo pipefail

CONFIG_FILE="/boot/firmware/config.txt"
if [[ ! -e "$CONFIG_FILE" ]]; then
  CONFIG_FILE="/boot/config.txt"
fi

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo scripts/enable_spi1_display.sh" >&2
  exit 1
fi

# Pip's display uses SPI1 MOSI/SCLK on physical pins 38/40, but uses a manual
# GPIO chip-select on GPIO6/physical pin 31 so it does not collide with the
# Freenove bumper-left GPIO16 claim.
if grep -q '^dtoverlay=spi1-1cs' "$CONFIG_FILE"; then
  echo "SPI1 1CS overlay already enabled in $CONFIG_FILE"
else
  printf '\n# Cleo Rover/Pip ST7789 display: SPI1 MOSI=GPIO20 pin38, SCLK=GPIO21 pin40; manual CS=GPIO6 pin31\ndtoverlay=spi1-1cs\n' >> "$CONFIG_FILE"
  echo "Enabled SPI1 1CS overlay in $CONFIG_FILE"
fi

echo "Reboot required. After reboot expect /dev/spidev1.0; Pip display CS is manually driven on GPIO6."
