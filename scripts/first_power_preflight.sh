#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ ! -x .venv/bin/cleo-rover ]]; then
  echo "Missing .venv/bin/cleo-rover. Run: python -m pip install -e '.[pi]'" >&2
  exit 2
fi

echo "== Cleo Rover first-power no-motor preflight =="
echo "This script does not arm motors or switch profiles."
echo

.venv/bin/cleo-rover health
.venv/bin/cleo-rover status
.venv/bin/cleo-rover sensors
.venv/bin/cleo-rover doctor
.venv/bin/cleo-rover preflight --mode presence

echo
echo "If preflight ok=true and motors_armed=false, safe next no-motor checks are:"
echo "  cleo-rover situation"
echo "  cleo-rover look-around"
echo "  cleo-rover motion-check"
echo "  cleo-rover remember-room --zone office"
