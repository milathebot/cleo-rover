#!/usr/bin/env bash
# Wake Pip up into a "living" autonomous being. Run this ON THE PI after `git pull`.
#
# What last run got wrong: the self-directed arbiter loop was off AND the inner
# drive (curiosity/boredom) could never reach the threshold to roam, so Pip only
# ever did reactive obstacle-avoidance when you drove it. The CODE fixes (boredom
# grows while quiet, curiosity holds at baseline, mood goes 'curious/seeking',
# patrol cadence) ship via `git pull` + a body restart -- no config needed. THIS
# script flips the per-robot local config flags that the committed defaults can't
# reach on their own:
#
#   stage 1 (default)  : directed roaming -- frontier VFH steering + occupancy
#                        mapping + wall-following + ROOM-TO-ROOM roaming (Pip may
#                        wander through doorways and learn/navigate rooms). Advisory
#                        only; the Pi-local reflex/cliff/bumper stops stay authoritative.
#   stage 2 (`arbiter`): the master switch -- let Pip self-drive (roam, act on
#                        curiosity, hug walls, cross rooms). ONLY enable while you are
#                        present and watching; the baby gate MUST be closed at the
#                        stairs (it + the cliff reflex are the room-to-room safety).
#
# Usage:
#   bash scripts/enable_living_mode.sh            # stage 1 only (safe, no self-drive)
#   bash scripts/enable_living_mode.sh arbiter    # stage 1 + 2 (Pip will self-drive)
#   bash scripts/enable_living_mode.sh off        # revert to boot-safe (arbiter off)
set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:-roam}"

# Find the live config the body actually loads: $CLEO_ROVER_CONFIG, else the first
# *local*.json under config/, else the committed cautious profile.
CFG="${CLEO_ROVER_CONFIG:-}"
if [ -z "${CFG}" ]; then
  CFG="$(ls config/*local*.json 2>/dev/null | head -1 || true)"
fi
[ -z "${CFG}" ] && CFG="config/rover.hardware.floor.cautious.json"
echo "config: ${CFG}  (mode: ${MODE})"

python3 - "${CFG}" "${MODE}" <<'PY'
import json, sys
path, mode = sys.argv[1], sys.argv[2]
c = json.load(open(path))
nav = c.setdefault("nav", {})
lf = c.setdefault("life_loop", {})
if mode == "off":
    lf["arbiter_enabled"] = False
else:
    nav["use_vfh_steering"] = True
    nav["mapping_enabled"] = True
    nav["wall_follow_enabled"] = True
    nav["cross_zone_roam_enabled"] = True
    if mode == "arbiter":
        lf["arbiter_enabled"] = True
json.dump(c, open(path, "w"), indent=2)
print("  nav.use_vfh_steering     =", nav.get("use_vfh_steering"))
print("  nav.mapping_enabled      =", nav.get("mapping_enabled"))
print("  nav.wall_follow_enabled  =", nav.get("wall_follow_enabled"))
print("  nav.cross_zone_roam      =", nav.get("cross_zone_roam_enabled"))
print("  life_loop.arbiter_enabled =", lf.get("arbiter_enabled", "(default False)"))
PY

echo
echo "apply it:  sudo systemctl restart cleo-rover-body.service"
echo "then watch the posture line:  journalctl -u cleo-rover-body.service -n 30 | grep 'autonomy posture'"
echo "and confirm what it'll do next:  curl -s localhost:8099/pip/arbiter | python3 -m json.tool"
