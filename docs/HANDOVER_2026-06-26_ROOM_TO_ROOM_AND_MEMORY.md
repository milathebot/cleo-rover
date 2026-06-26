# Handover — 2026-06-26 — Room-to-room roaming + place-aware memory (no LiDAR/encoders)

Goal from the owner: with the stairs guarded by a closed baby gate, make Pip as
autonomous and as good at navigation + memory as possible *within the current
hardware* (single front HC-SR04 on a pan turret, camera, 3 downward cliff IR, open-
loop odometry — no encoders/IMU/LiDAR), and clean up any code bloat. No hardware was
attached this session (Pi powered down): code/config/tests + the wake-up script.

## The honest capability (what room-to-room means here)
There is no metric SLAM. Room-to-room rides entirely on the **topological place
graph** that already existed: Pip fingerprints places (sonar signature + camera
histogram + floor IR), recognises them by ≥2-of-3 voting, and **relocalises at every
place so open-loop drift never compounds across a route**. Physical safety is the
**closed baby gate + the authoritative cliff reflex** — never a label check. Expect
~roaming-between-distinct-rooms-works, with the occasional "I got lost, can you help"
when a doorway is tight or two rooms look alike. That's the realistic ceiling without
better sensors, and it's genuinely useful.

## What was missing (root cause) and what changed
The topo machinery worked, but three gaps made it inert:
1. **`current_zone` never tracked the graph** — it was only ever set by an explicit
   command, so Pip always thought it was in the office. → New `sync_current_zone_to_place()`
   snaps `current_zone` to a recognised, *named* place during `topo_automap` and
   return-home relocalisation. (Anonymous `place-N` nodes don't move the label.)
2. **`approved_zones=["office"]` hard-blocked leaving the office.** → New
   `nav.cross_zone_roam_enabled`: when on, the soft zone-permission gate lifts (gate +
   cliff are the safety). Default OFF in code (tests/bench unchanged); ON in the
   hardware profile.
3. **No way to teach/name rooms or navigate to them.** → `return_home_task(goal=…)`
   already traverses a topo route to ANY named place; now wired up:
   - Teach a room: `POST /pip/place/name?name=kitchen` or say **"this room is the
     kitchen"** / "remember this place as the office" / "you are in the hallway".
     Renames the current place node + sets the zone. Drive Pip to each room once and
     name it — that's the whole setup.
   - Navigate there: say **"go to the kitchen"** (or set an explore_zone goal). With
     roaming on, room destinations no longer "require human help" (stairs/outdoors
     still always do); `pursue_goal` navigates the topo route, then explores on arrival.

## Memory made place-aware (offline, no LLM)
- **Memory-driven roaming**: `explore.place_interest()` scores rooms by age-decayed
  pet/person sightings; every 3rd autonomous patrol the arbiter may navigate to the
  most interesting *other* learned room (`pick_roam_target_zone`). So Pip drifts back
  toward where life happens instead of wandering one room forever.
- **Place-aware recall**: `GET /map/zone/{zone}` and voice **"what's in the kitchen"** /
  "what did you see in the office" → `zone_memory_summary()` lists what Pip remembers
  per room. Sightings are tagged with `current_zone`, which now actually tracks rooms.
- The wake-loop "heard" speech fix from the prior pass means voice interactions feed
  memory too.

## Code-health finding (the owner asked about bloat)
Audited the ~45 modules + 3.9k-line service.py for redundancy. Verdict: **leaner than
feared.** The "dead" candidates flagged by analysis were wrong — `brain.py`'s
`choose_body_intent` is live (service.py) and `BrainLoop` is the entry point of the
optional PC-brain CLI (`python -m rover.brain`); both stay. No risky refactor was done.
Real, low-value-but-noted opportunities for later: a shared `constants.py` for the
range thresholds scattered across `awareness.py`/`brain.py`/`topo_map.py`, and the
`calibrate.py` (wizard) vs `calibration.py` (gates) naming. Left as-is to avoid churn.

## Next power-on (unchanged flow, now includes room-to-room)
1. `git pull` → `sudo systemctl restart cleo-rover-body.service`; check the posture
   line: `journalctl -u cleo-rover-body.service -n 40 | grep 'autonomy posture'`
   (now shows `room_to_room=…`).
2. `bash scripts/enable_living_mode.sh` → restart  *(directed + room-to-room roaming on
   the live local config; still no self-drive).*
3. **Show Pip around**: drive it (dashboard camera/teleop) into each room and name it —
   say or `POST /pip/place/name?name=…`. This builds the place graph + edges.
4. **Gate closed, you present and watching**: `bash scripts/enable_living_mode.sh arbiter`
   → restart. Pip will roam, cross rooms, revisit interesting ones, and you can say
   "go to the kitchen". `off` reverts to boot-safe.

## Risks / expectations (ranked)
1. **Drift before first relocalise** — if the next room's fingerprint is too similar or
   a doorway is tight, recognition can miss; the route aborts after 3 misses and Pip
   asks for help (it won't blind-wander). Mitigate by naming distinct, separated rooms.
2. **Look-alike rooms** collide on sonar; camera histogram + floor IR usually break the
   tie. Re-teach/rename if two rooms merge.
3. **The gate is the real safety.** cross_zone_roam only lifts a soft label check;
   keep the baby gate closed whenever the arbiter is on. Stairs/outdoor destinations
   always refuse to auto-drive regardless.

## Tests
+10 in `tests/test_room_to_room.py` (place-interest scoring/decay, zone-tracking,
room naming, the gate lifting only when roaming is on, the stairs-always-need-help
policy, voice parsers, per-room recall). Suite: **424 pass.** Code defaults stay
conservative so sim/tests keep the single-room widest-gap behaviour.
