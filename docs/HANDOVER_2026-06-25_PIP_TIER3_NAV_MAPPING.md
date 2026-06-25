# Handover: Tier 3 — Pip's proprietary mapping & navigation brain

This adds the "make Pip actually smart" navigation layer on top of the Tier 1+2
autonomy: a **body-frame rolling occupancy grid**, **VFH+ steering**, **frontier
exploration**, **wall-following**, **optical-flow stall confirmation**, a
**topological place graph** with drift-reset, and **memory consolidation**.

It is built for *our* hardware — **no LiDAR, no encoders, no IMU** — and follows
the published cheap-robot playbook (Thrun occupancy grids, Borenstein/Koren VFH+,
Yamauchi frontiers, topological SLAM, Lucas-Kanade flow). When you add the LiDAR
later, it slots in as just another range source for the same grid + VFH.

**Everything here is ADVISORY.** It decides *where/how* to move; it can only ever
make Pip do **less**. The Pi-local reflex/cliff/bumper stops, movement grants, and
`validate_intent` remain authoritative and untouched. All logic is verified in sim
+ unit tests (`python -m pytest -q`, 254 passing). Behaviour-changing flags ship
**OFF** so the branch merges dark; you enable them after light supervised testing.

> Golden rules (unchanged): Pi-local safety is authoritative; nothing (nav, vision,
> mind, voice) relaxes a reflex; movement needs a grant **and** armed motors.

---

## What got added (and why it's the right design for no-LiDAR)

| Module | What it does | Why this approach |
|---|---|---|
| `rover/occupancy.py` | Robot-centric **rolling log-odds grid** (~4 m) with a sonar **inverse sensor model** (wide FREE cone, narrow OCCUPIED core; max-range never paints an obstacle) + **frontier detection**. | A *global* metric map smears within metres of open-loop drift. A small rolling grid with a tight clamp self-heals. (Thrun ch.9; Nav2 rolling costmap.) |
| `rover/vfh.py` | **VFH+** polar-histogram steering from one sonar sweep: robot-width enlargement, threshold **hysteresis**, goal/commitment **cost function**. | Body-frame ⇒ drift can't corrupt one decision. Hysteresis kills the single-threshold oscillation that turned Pip away ~20 cm before doorways. (Borenstein/Koren; Ulrich/Borenstein VFH+.) |
| `rover/wall_follow.py` | **PD wall-follower** + inside/outside-corner handling. | Most reliable systematic coverage without pose — it references the physical wall. Perimeter-follow returns to start (maze wall rule). |
| `rover/vision_service.py` (extended) | Sparse **Lucas-Kanade optical flow** → moving/stalled, yaw sign, looming TTC. Pure decision logic + a guarded cv2 capture path. | Confirms a stall (open-loop "I moved" is a guess) and adds a looming stop the narrow sonar beam misses. ~15–25 Hz on a Pi 4. |
| `rover/topo_map.py` | **Topological place graph**: place = fused fingerprint (sonar signature + visual histogram + IR context), edge = transition. Recognition by **≥2-of-3 voting**, graph route planning, duplicate merge. | Relocalising at each node bounds drift by *landmark spacing*, not odometry quality. The correct map model for a no-odometry robot. |
| `rover/consolidation.py` | Episodic sightings → durable **semantic facts** (decay / reinforce / promote / prune). | A small, self-cleaning knowledge base ("the charger is in the office") that forgets gracefully when the world changes. |

New config block: `nav` (`rover/config.py: NavConfig`) — all tunables + flags.
New persistence: `semantic_facts` table; topo graph stored under the `topo_map` kv key.

### New endpoints (all sim-safe; movement still gated)

- `POST /nav/plan` — sweep → **VFH+ steering bearing + occupancy-grid frontiers** (read-only advice).
- `GET /nav/grid`, `POST /nav/grid/reset` — the persistent rolling grid (stats + ASCII map).
- `POST /topo/observe` — fingerprint the current place, add/recognize it, link an edge.
- `GET /topo/graph`, `GET /topo/plan?to=<name>`, `POST /topo/merge`.
- `POST /memory/consolidate`, `GET /memory/facts`.
- `POST /vision/flow` — optical-flow availability/advisory (reports unavailable off-Pi).
- `POST /tasks/wall-follow?side=left&allow_movement=…` — PD wall-follow task (flag-gated).

---

## Enable on hardware — supervised, in this order

Do **§0–§8 of the main enable doc first** (`HANDOVER_2026-06-25_PIP_ENABLE_ON_HARDWARE.md`):
sensors verified, **cliff/bumper reflexes on**, odometry calibrated. Tier 3 sits on
top of that floor. Then:

### A. Read-only first (no new movement) — safe to do immediately
```bash
# These never move Pip; they just sweep + think. Great first confidence check.
cleo-rover-... POST /nav/plan   '{"zone":"office","angles":[-60,-40,-20,0,20,40,60]}'
#   -> check steering.chosen_bearing_deg points at the real opening, and
#      frontiers point toward unexplored space.
curl -X POST localhost:8099/topo/observe -d '{"zone":"office"}'   # fingerprint here
curl localhost:8099/topo/graph                                    # one place so far
curl -X POST localhost:8099/memory/consolidate                    # build facts from memory
```
Watch a few `/nav/plan` calls as you carry Pip around. If the steering bearing and
frontiers consistently make sense, the sensing + VFH are sound.

### B. Calibrate the nav params to your room + robot
In `config` → `nav`:
1. **`vfh_robot_radius_cm` / `vfh_safety_cm`** — set to Pip's true half-width + a
   margin. Too small ⇒ clips doorframes; too big ⇒ won't thread real doorways.
2. **`vfh_d_max_cm`** — your HC-SR04 trust horizon (~150–200 cm indoors).
3. **`grid_cell_cm` / `grid_size_cells`** — 10 cm / 41 (≈4 m) is a good default.
4. **`vfh_tau_low/tau_high`** — if Pip dithers, widen the gap; if it ignores real
   obstacles, lower them. (They're coupled to `vfh_a`/`d_max`.)

### C. Turn on VFH steering for exploration (supervised, hand on stop)
```jsonc
"nav": { "use_vfh_steering": true }   // reactive-explore now steers via VFH+
```
Run `/tasks/reactive-explore` with `allow_movement=true` in a clear area. Each turn
result carries a `vfh` block so you can see what it chose and why. Compare against
the old behaviour (flag off) — keep whichever threads doorways better.

### D. Turn on persistent mapping (so the grid accumulates across moves)
```jsonc
"nav": { "mapping_enabled": true }
```
`/nav/grid` now builds up as Pip drives (pose fed from the calibrated motion model).
**Expect drift** beyond ~3–4 m — that's why it's a *rolling* grid; it's for "what's
around me," not a floor plan. Reset anytime with `POST /nav/grid/reset`.

### E. Wall-following coverage
```jsonc
"nav": { "wall_follow_enabled": true }
```
`POST /tasks/wall-follow?side=left&allow_movement=true`. Tune `wall_setpoint_cm`,
`wall_kp/kd` (kd-dominant — sonar is slow), and the corner thresholds on the floor.

### F. Build the topological map of your home
Drive room to room; at each stable spot call `POST /topo/observe` (give a `name`
the first time: `?name=kitchen`). Pip fingerprints the place and links an edge from
the last one. Revisits **relocalize** (drift reset) instead of spawning duplicates.
Then `GET /topo/plan?to=kitchen` returns the action sequence. Run `POST /topo/merge`
occasionally to fuse any near-duplicate "ghost" rooms.

### G. Optical-flow stall confirmation (needs the camera + OpenCV)
```bash
pip install -e '.[vision]'     # now also pulls opencv-python-headless on aarch64
```
```jsonc
"nav": { "flow_stall_enabled": true }
```
`POST /vision/flow` should report `available: true`. Calibrate `flow_move_thresh_px`
on the bench: log median flow parked (noise floor) vs at min speed, set the threshold
~3× the noise floor. Flow then confirms stalls (so Pip stops trusting phantom motion)
and raises a looming alarm — advisory, never a reflex override.

### H. Memory consolidation runs itself
`consolidation_enabled` is on by default; the life heartbeat distills sightings into
facts every `consolidation_interval_heartbeats` ticks (hardware-only auto-start).
`GET /memory/facts` to see them. Tune `consolidation_promote_n` (sightings before a
landmark becomes a fact).

---

## Safety invariants (asserted by tests, true across Tier 3)

1. No nav layer can move in bench profile without a grant + armed motors.
2. The reflex/cliff/bumper stops fire independently of VFH/grid/topo/flow.
3. VFH/grid/optical-flow are **body-frame or advisory** — open-loop drift cannot
   make them *relax* a guard, only add caution (`vision_block`, looming, stall).
4. Topo/consolidation/`/nav/plan` are read-only or non-motor; they never drive.

## Known follow-ups (tracked, not blockers)
- Feed a future LiDAR into the same `OccupancyGrid` ISM + `vfh.steer` (drop-in).
- Tangent-Bug wrapper around VFH for "go to remembered landmark around an obstacle."
- Visual place recognition (HSV histogram / ORB) to strengthen topo relocalization
  beyond the sonar signature (the topo graph already accepts a `hist_desc`).
- Tier 2C movement-grant per-task ownership (carried over from the prior handover).
