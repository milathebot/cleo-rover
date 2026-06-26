# Handover — operating Pip (Cleo Rover Mk1) as the Hermes mind

**Audience:** Hermes (the PC/cloud agent that will pull + merge this PR and then *run*
Pip on the real Raspberry Pi 4B + Freenove FNK0043 chassis).
**You are the MIND. Pip is the BODY.** This document is your operating manual:
the architecture, the safety contract you must never break, how to bring Pip to
life on hardware, the exact API you drive it through, and how to keep it alive.

Read this **once** before you first operate Pip's motion (and re-skim after a pull
that changes it). You do **not** re-read it per command — the per-action safety
checks are enforced at runtime by the Pi (grant + armed motors + the calibration
gate + the reflex), not by re-reading this doc. For the exact cold-boot → alive
sequence, follow [`docs/POWERUP_RUNBOOK.md`](docs/POWERUP_RUNBOOK.md).

---

## 0. The one paragraph that matters most

Pip is **autonomous and safe without you**. A Pi-local reflex + behavior stack
keeps it from hurting itself and lets it roam, map, express, and self-preserve
even with you offline. **You are an enhancement, not a requirement.** Everything
you send is *advisory*: the Pi validates it, may refuse it, and falls back to its
own deterministic policy. **You can only ever make Pip do *less* than its safety
floor allows — never more.** Internalize that and you cannot drive Pip into
trouble; ignore it and you will be (correctly) refused.

---

## 1. Architecture: the dual-process body

```
            ┌────────────────────────────────────────────────────────────┐
 YOU →      │  MIND (Hermes, this agent)         slow, optional, advisory  │
 (0.1–1 Hz) │  in:  world-state packet + persona                          │
            │  out: ONE intent from a closed allow-list (bounded params)  │
            └───────────────────────────┬────────────────────────────────┘
                                         │  intent JSON (advisory)
            ┌────────────────────────────▼───────────────────────────────┐
 PI —       │  validate_intent(): allow-list + clamps + REFUSE on         │
 VALIDATION │  no-grant / disarmed / panned-turret / obstacle / low-batt. │
 (AUTHOR.)  │  Refusal → falls back to ↓ . You never touch motor PWM.     │
            └───────────────┬──────────────────────────┬──────────────────┘
                            │ validated bounded burst   │ default / offline / refusal
            ┌───────────────▼─────────────┐  ┌──────────▼─────────────────┐
 PI —       │ Behavior arbiter + nav       │  │ Deterministic local policy │
 AUTONOMY   │ (return-home, patrol+map,    │  │ (always available)         │
 (ALWAYS-ON)│ socialize, cruise, VFH+)     │  └────────────────────────────┘
            └───────────────┬─────────────┘
            ┌───────────────▼───────────────────────────────────────────┐
 PI — REFLEX│ 30ms watchdog · 20ms drive-monitor · ultrasonic reflex ·    │ AUTHORITATIVE,
 (NEVER     │ bearing guard · cliff/bumper reflex · movement-grant gate · │ network-independent,
  VETOED)   │ command watchdog · bounded motion budget · battery cutoff   │ beats every command
            └────────────────────────────────────────────────────────────┘
```

- **Reflex tier** runs on the Pi, hard real-time, and **cannot be relaxed by you,
  vision, voice, or the nav layer.** It stops the motors for: an ultrasonic
  reading below the hard floor, an unknown forward range (fail-closed), a turret
  panned off-center during a forward command (bearing guard), a cliff/bump (when
  enabled), an expired/absent movement grant, or a motion that overran its
  deadline.
- **Autonomy tier** is Pip's own brain stem: a behavior arbiter that picks one
  action per tick from mood/energy/curiosity/battery/people/time, executed via
  safe primitives. It works with you offline.
- **Mind tier (you)** supplies high-level intent, goals, persona, and voice. The
  Pi treats you as one more advisory input.

---

## 2. Hard rules — do not violate

These exist for concrete reasons (one turret-mounted sonar, open-loop motion, no
encoders), so apply them with judgment rather than as rote ceremony — the *why* is
given inline. The Pi enforces them at runtime; you don't need to re-derive them per
command.

1. **Never assume a command moved the robot.** Read state back; honor refusals.
2. **Movement requires three things simultaneously:** an *active movement grant*,
   *armed motors*, and a *clear reflex*. You can request a grant; you cannot arm
   motors (that is a deliberate physical/profile decision by the owner) and you
   cannot override the reflex.
3. **One intent at a time, from the allow-list** (§5). Out-of-range params are
   clamped; unknown intents become `idle`.
4. **Never fabricate sensor values.** Decide only from the world-state packet /
   `/health/composite`. If unsure, prefer `scan`/`observe` over moving.
5. **Obey the owner.** Quiet hours, do-not-disturb, and explicit stop always win.
   Destinations needing a human (doors, outdoors) must *ask*, not act.
6. **The reflex/cliff/bumper stops and `validate_intent` are the floor.** If you
   ever find a way to move without a grant+armed+clear, that is a bug — report it,
   do not exploit it.

---

## 3. Pull, merge, install (on the Pi)

This PR is branch `feat/autonomous-embodied-agent`.

```bash
# merge the PR into your main line, then on the Pi:
cd ~/cleo-rover && git pull
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[pi]'        # core + GPIO/SPI/I2C + numpy
pip install -e '.[vision]'    # optional: on-Pi camera detector + optical flow (TFLite, OpenCV)
pip install -e '.[voice]'     # optional: offline wake-word + STT
python -m pytest -q           # expect ~365 passing (sanity)
```

Run the body service (this is what you talk to over HTTP, default port 8099):

```bash
# bench / sim (no motors): safe to explore the API
CLEO_ROVER_MODE=sim uvicorn rover.service:app --port 8099

# hardware, motors disarmed (presence) — sensors + expression, no driving:
CLEO_ROVER_CONFIG=config/rover.hardware.presence.json CLEO_ROVER_MODE=hardware \
  uvicorn rover.service:app --port 8099

# hardware, motor-armed floor profile — ONLY after calibration (§4):
CLEO_ROVER_CONFIG=config/rover.hardware.floor.cautious.json CLEO_ROVER_MODE=hardware \
  uvicorn rover.service:app --port 8099
```

On the deployed rover the body runs as a systemd unit, **`cleo-rover-body.service`**
(not a hand-started `uvicorn`). Operate it with:

```bash
sudo systemctl restart cleo-rover-body      # apply a pull or a config edit
journalctl -u cleo-rover-body -f            # logs
sudo cat /proc/$(pgrep -f 'uvicorn rover.service')/environ | tr '\0' '\n' | grep CLEO_ROVER  # which config it booted
```

After a `git pull`, the running process keeps the **old** code in memory until you
restart the unit — new endpoints 404'ing while `/health` works is the classic
"didn't restart" symptom. Make sure exactly one unit owns `:8099`
(`sudo ss -ltnp 'sport = :8099'`); a stale second uvicorn will keep serving old code.

All your control is HTTP against `http://<pi>:8099`. There is also a CLI
(`cleo-rover ...`) and an operator web panel at `/`.

---

## 4. Bring-up: the path from "merged" to "alive"

**Do not skip this. Pip ships with every risky flag OFF.** The full, ordered
checklist with the exact measurements is in
[`docs/HANDOVER_2026-06-25_PIP_FNK0043_AUDIT_AND_BRINGUP.md`](docs/HANDOVER_2026-06-25_PIP_FNK0043_AUDIT_AND_BRINGUP.md);
`GET /calibration` returns the same checklist plus auto-checkable readiness gates
and a `ready_for_supervised_drive` boolean. The condensed sequence:

1. `i2cdetect -y 1` → confirm `0x40` (PCA9685) and `0x48` (ADS7830).
2. **Set `sensors.pcb_version`** (1 or 2) in the config — a wrong value misreads the
   battery ~33%. Confirm with a multimeter vs `GET /battery` voltage.
3. Verify all 4 wheels roll forward on a forward command.
4. **Verify pan: command pan +30° → the sonar must rotate RIGHT.** (A prior board
   bug inverted this; the code is fixed but verify the physical direction.)
5. Center the turret, confirm ±70° clears the chassis.
6. Calibrate ultrasonic read latency → set `nav.ping_latency_ms` / `nav.cruise_react_ms`.
7. IR over white floor / black line / a real table-edge void → set `safety.line_drop_value`.
8. Coast distance at duty 0.3 → set `nav.cruise_coast_cm`.
9. UMBmark square → tune `odometry.cm_s_per_duty` (~33) + `odometry.deg_s_per_turn_duty` (~200).
10. `dtparam=spi=on` → RGB lights (GRB order).
11. **Enable reflexes LAST**, after 4 & 7 pass: `safety.cliff_reflex_enabled: true`
    (with the measured `line_drop_value`). Leave `bumper_reflex_enabled` off — the
    FNK0043 has no bump switches.

**Gate:** steps 1–7 before any powered drive; 8–11 before continuous cruise.
`GET /calibration` → `ready_for_supervised_drive` must be true before you grant motion.

---

## 5. Connecting as the mind

### 5.1 Point Pip at you
Set env on the body service (never commit keys). Pip uses an OpenAI-compatible chat
endpoint. Any of three name sets work, first wins: `MIND_*` → `HERMES_*` →
`CLEO_ROVER_HERMES_*` (the last are the **same names the Telegram agent +
vision-label already use**, so one cred set wires the whole rover):

```bash
# project-prefixed names — reuse what the Telegram agent already has:
export CLEO_ROVER_HERMES_API_BASE=http://<hermes-host>:<port>/v1
export CLEO_ROVER_HERMES_API_KEY=...
export CLEO_ROVER_HERMES_MODEL=hermes-agent
```

**Deployed pattern (recommended).** Both `cleo-rover-body` and the Telegram agent
read a shared, root-only **`/etc/cleo-rover/hermes.env`** (each has a
`EnvironmentFile=/etc/cleo-rover/hermes.env` drop-in). If your Hermes runs behind a
`trycloudflare` quick-tunnel, its URL **rotates every launch** — so refreshing the
endpoint is a one-file edit, not a hunt:

```bash
sudo tee /etc/cleo-rover/hermes.env >/dev/null <<'EOF'
CLEO_ROVER_HERMES_API_BASE=https://<new-tunnel>/v1
CLEO_ROVER_HERMES_API_KEY=<key>
CLEO_ROVER_HERMES_MODEL=hermes-agent
EOF
sudo chmod 600 /etc/cleo-rover/hermes.env
sudo systemctl restart cleo-rover-body cleo-rover-telegram-agent
```

(For a one-off / non-deployed run you can instead `sudo systemctl edit cleo-rover-body`
and add the `Environment=` lines directly.)

`GET /mind/status` → `configured: true` when set; confirm end-to-end with
`POST /mind/step?zone=office` → expect `source: "mind"` (not `deterministic_fallback`).
With nothing set, Pip runs fully offline on its deterministic policy (by design).

### 5.2 The intent contract (this is your whole motor vocabulary)
When asked (`POST /mind/step?zone=<zone>`), the Pi sends you a world-state packet +
Pip's persona and expects **ONE JSON object, no prose**:

```json
{ "intent": "status|stop|scan|look|say|mood|move_step|rotate_step|idle|set_goal",
  "mood":   "happy|curious|alert|thinking|focused|... (optional)",
  "speech": "one short spoken line (optional)",
  "params": { "forward_cm": -12..12, "deg": -35..35, "pan_deg": -80..80,
              "zone": "office", "angles": [-35,0,35],
              "goal_kind": "explore_zone|find_person|return_to|observe", "target": "kitchen" },
  "reason": "one short clause" }
```

What the Pi does with it:
- **Clamps** every param to the bounds above; unknown intents → `idle`; unknown
  param keys dropped.
- **`validate_intent` then REFUSES** and falls back to local policy when:
  - `move_step`/`rotate_step` and there is **no active grant**, **motors disarmed**,
    or **bench_safe** profile;
  - `move_step` and the **turret is panned >5°** (the single sonar would be reading
    a side, not ahead — `look` pan 0 first);
  - `move_step` and the **front clearance is unknown or < ~120 cm** (supervised
    autonomy is conservative; the reflex is a last resort, not the normal stop).
- **`set_goal`** stores a persistent mission the *arbiter* executes across ticks
  (so it survives you going offline). Goal kinds: `explore_zone`, `find_person`,
  `return_to`, `observe`.

**Practical guidance for you:** prefer `scan` / `look` / `observe` when uncertain;
emit `move_step`/`rotate_step` only when the packet clearly shows clearance and a
centered turret; use `set_goal` for anything multi-step and let the arbiter run it;
use `mood`+`speech` freely (they drive the RGB "face" and TTS, never motion).

### 5.3 Two ways to drive Pip's mind loop
- **`POST /mind/step?zone=office`** — one deliberative step: Pip builds the packet,
  asks you, validates, dispatches or falls back. Call this at your cadence (0.1–1 Hz).
- **Let the arbiter run (recommended for "living"):** enable the autonomy loop
  (§7) and use `set_goal` + occasional `/mind/step` for high-level steering. The
  arbiter handles moment-to-moment behavior; you supply intent and personality.

---

## 6. Movement + grants (the part people get wrong)

Motion needs an **active grant**. A grant is task-scoped and time-boxed:

```bash
POST /movement/grant
{ "task": "explore", "allow_movement": true, "duration_seconds": 300,
  "max_linear": 0.3, "max_turn": 0.65 }
POST /movement/revoke         # ends it, stops the robot
GET  /movement/status
```

- Grants carry an **`owner`**. The continuous-cruise loop self-grants `owner:"cruise"`
  and **yields** if another task takes the grant — so don't fight it; revoke or let
  it finish.
- A grant published by a self-granting task is only `active` when motors are armed,
  so in sim/disarmed you'll see `active:false` (honest, not a bug).
- `move_step`/`rotate_step`/all `/tasks/*` motion still pass through
  `guarded_drive` → reflex + grant + armed + obstacle checks every pulse.

---

## 7. Running Pip as a living being

### 7.1 Wake it up
```bash
POST /pip/live?on=true      # starts heartbeat + behavior arbiter + RGB expression (hardware)
POST /pip/live?on=false     # pause + stop
```
On hardware the loops also auto-start per their flags. To make the arbiter
self-direct, set `life_loop.arbiter_enabled: true` in the config (default OFF; flip
it only after §4 and a supervised first run).

### 7.2 The behavior arbiter (Pip's autonomy)
Each tick it picks ONE behavior by priority:
`rest` (sleep/quiet) → `return_to_charger` (battery critical/low + dock known) →
`hold` (fresh hazard) → `observe` (quiet hours / DND) → `socialize` (person near) →
`pursue_goal` (your `set_goal`) → `patrol` (curious/bored + free to move) → `observe`.
- Drive it manually: `POST /pip/arbiter/tick?allow_movement=true`.
- Inspect the *next* choice + why: `GET /pip/arbiter` and `GET /health/composite`.
- **Self-preservation is real:** on a debounced critical battery it traverses the
  topo graph to a place named like "charger"/"dock" and docks; if it can't find or
  reach one, it raises a rescue interrupt (§9) asking you to help dock.

### 7.3 Goals (your main steering lever)
```bash
POST /pip/goal { "kind": "explore_zone", "target": "office", "step_budget": 12 }
GET  /pip/goal
DELETE /pip/goal
```
Or via a `set_goal` intent. The arbiter pursues the active goal and retires it when
`progress` reaches `step_budget`. A destination wish in natural language (via
`/pip/command`) becomes an `explore_zone` goal automatically — *unless* it needs a
human (a door/room transition/outdoors), in which case Pip asks instead of acting.

### 7.4 Navigation surfaces
- `POST /nav/plan {zone, angles}` — **read-only smart-nav advice**: VFH+ steering
  bearing + occupancy-grid frontiers. Great for "what's the smart move?" without moving.
- `POST /tasks/return-home?goal=charger&allow_movement=true` — traverse the place
  graph to a goal, relocalizing at each node; aborts + asks for help if lost.
- `POST /topo/observe?name=kitchen` — fingerprint the current place into the graph.
  **The graph also builds itself during patrol**, but observe key places (esp. the
  charger: `?name=charger`) so return-home has anchors.
- `GET /topo/graph`, `GET /topo/plan?to=kitchen`, `POST /topo/merge`.
- `POST /pip/cruise?dry_run=true` — show the continuous-motion decision Pip *would*
  make (no movement); `?on=true` (hardware + `nav.continuous_motion_enabled`) for
  smooth non-stop roaming. `GET /nav/grid` for the rolling occupancy map.
- `POST /tasks/wall-follow`, `POST /tasks/reactive-explore`,
  `POST /tasks/little-being-loop` — lower-level movement tasks (grant-gated).

### 7.5 Expression (no display yet → RGB is the face)
- `GET /pip/rgb-affect` — the color/pattern Pip is showing (mood→hue,
  energy→breathe/pulse, low-batt amber, alert red, charging green). A loop animates
  it on hardware.
- `mood` + `speech` intents set the affect + TTS voice.
- A display exists in the code (ST7789) but **the owner does not own one yet** —
  ignore display correctness; everything routes through RGB + voice.

### 7.6 Voice + vision (optional, offline-first)
- Voice: `cleo-rover-voice` daemon (wake-word → STT → `/pip/command`); `/hearing/listen`.
  Talking never moves the robot.
- Vision: `/vision/analysis` (external labels), on-Pi TFLite detector when the
  `vision` extra + a model are present, `/vision/flow` (optical-flow stall/looming).
  Advisory only — vision can add caution, never relax the reflex.

### 7.7 Knowing how Pip is
- **`GET /health/composite`** — the single "is Pip OK / what is it doing / can it
  move now?" call: battery SOC + charging + warn/critical, mood/energy, movement
  permission (+grant owner), active goal, the arbiter's current choice, capability
  level, every subsystem readiness bit, version, and a top-level `ready_to_move` +
  `blockers`. **Poll this.**
- `GET /health/degradation` — capability tier (`full` / `scan_only` / `turret_only`
  / `stopped`) + reasons. If it's not `full`, respect it.
- `GET /battery`, `GET /tasks/history`, `GET /life/diary` (Pip's truthful
  first-person inner-life narrative — good for a status voice line), `GET /situation`,
  `GET /sensors`, `GET /doctor`, `GET /preflight?mode=floor-cautious`.

---

## 8. Config + flags (what's off, and when to turn it on)

Config is `config/*.json`; pick with `CLEO_ROVER_CONFIG`. Sections:
`safety`, `sensors`, `odometry`, `nav`, `vision`, `mind`, `voice`, `life_loop`,
plus hardware maps. **Default-OFF flags and their gate:**

| Flag | Turn on when… |
|---|---|
| `safety.cliff_reflex_enabled` | IR polarity verified on a real edge (calib §4.7) |
| `safety.bumper_reflex_enabled` | only if you physically add + verify bump switches |
| `life_loop.arbiter_enabled` | after a supervised first floor run; this makes Pip self-direct |
| `nav.continuous_motion_enabled` | after coast distance calibrated; enables smooth cruise |
| `nav.mapping_enabled` | to accumulate the persistent occupancy grid across moves |
| `nav.wall_follow_enabled` | to allow the wall-follow coverage task to drive |
| `nav.flow_stall_enabled` | with the `vision` extra installed (camera + OpenCV) |

**On by default (non-motor / safe):** `nav.topo_enabled`,
`nav.consolidation_enabled`, `life_loop.rgb_expression_enabled`, the life heartbeat
(hardware). **Must set per board:** `sensors.pcb_version`.

Key tunables you may adjust: `safety.reflex_hard_cm`, `safety.front_stop_distance_cm`,
`safety.forward_cone_guard_deg` (bearing guard, 5°), `life_loop.return_to_charger_min_battery`,
`life_loop.quiet_hours`, `nav.cruise_max_linear`, `nav.vfh_robot_radius_cm`/`vfh_d_max_cm`.
A `RoverConfig` validator enforces the cruise braking invariant
(`cruise_coast_cm + cruise_margin_cm < reflex floor`) across all profiles.

---

## 9. State, persistence, and rescue

**Survives a reboot** (SQLite at `life_loop.data_path`, default `data/rover.sqlite`):
events, spatial memory, **semantic facts** (consolidated landmark knowledge), the
**topo place-graph**, the **current place pointer** (`last_topo_node`), the active
goal, `pip_state` (mode/mood/zone), autonomy state + behavior cooldowns, task
history, pending interrupts. So "power up and return home" works after a restart.

**Ephemeral by design** (rebuilt each boot): the rolling occupancy grid, the cruise
perception snapshot, the battery estimator's running state. Pip re-scans before
smooth motion after a boot — expected.

**Rescue / interrupts:** when Pip is cornered, lost on the way to the charger, or
low with no reachable dock, it enqueues a high-priority interrupt. **Watch
`GET /pip/interrupts?mark_delivered=true`** and act on rescues (guide it, clear a
path, or physically dock it). This is the main way Pip asks *you* for help — a core
part of "thinks independently while still listening to me."

**Graceful degradation:** if a subsystem fails (e.g. ultrasonic down), Pip drops to
a reduced capability tier (`scan_only`/`turret_only`/`stopped`) instead of acting
blind. Honor `/health/degradation` — don't request drives it has degraded out of.

---

## 10. File map (where to look)

- `rover/service.py` — the FastAPI body service; every endpoint + the background
  loops (watchdog, drive-monitor, heartbeat, arbiter, perception, cruise, RGB).
- `rover/drivers.py` — `RoverBody`: guarded_drive, watchdog, reflex + **bearing guard**.
- `rover/freenove.py`, `rover/peripherals.py` — FNK0043 hardware (PCA9685 motors/servos,
  HC-SR04, IR, ADS7830 battery, WS2812 RGB).
- `rover/arbiter.py` — pure behavior selection. `rover/autonomy.py` — emotion engine.
- `rover/mind.py` — your contract (allow-list, clamps, the call to you).
  `rover/supervisor.py` — `validate_intent` (the refusal gate).
- Nav: `rover/navigation.py`, `vfh.py`, `occupancy.py`, `wall_follow.py`,
  `perception.py`, `cruise.py`, `topo_map.py`, `topo_executor.py`, `explore.py`,
  `odometry.py`, `line_follow.py`.
- State/health: `rover/battery.py`, `degrade.py`, `calibration.py`, `diary.py`,
  `consolidation.py`, `persistence.py`.
- Expression/voice/vision: `rover/rgb_affect.py`, `choreo.py`, `renderer.py`,
  `voice_daemon.py`, `vision_service.py`.
- Config: `rover/config.py` + `config/*.json`.
- Deeper docs: `docs/HANDOVER_2026-06-25_PIP_FNK0043_AUDIT_AND_BRINGUP.md` (calibration),
  `docs/HANDOVER_2026-06-25_PIP_TIER3_NAV_MAPPING.md` (nav + cruise enable),
  `docs/HANDOVER_2026-06-25_PIP_ENABLE_ON_HARDWARE.md` (general enable),
  `docs/HANDOVER_2026-06-25_PIP_AUTONOMY_AUDIT.md` (architecture rationale).

---

## 11. Known limitations / not-done (so you don't trust what isn't there)

- **No display owned** — RGB + voice are the only expression channels right now.
- **No encoders/IMU/LiDAR** — all distance/heading is open-loop *guesses*; never
  treat `travelled_cm`/pose as truth. Drift is bounded by re-recognizing places,
  not by odometry. (A LiDAR is planned; it will slot into the same occupancy grid.)
- **Hardware calibrations still required** before trusting: battery sag
  (`BatteryEstimator(sag_k=…)`), cruise coast distance, odometry coefficients.
- **Bumpers don't physically exist** on the FNK0043 — keep that reflex off.
- Continuous cruise + wall-follow + mapping are built + tested in sim but only run
  on hardware behind their flags; bring them up one at a time, supervised.
- Tracked software follow-ups (non-blocking): uniform task error envelopes,
  per-person enrollment/bonding, idle fidgets, RGB driver fallback for other board
  revisions.

---

## 12. Quick reference — the endpoints you'll use most

| Goal | Call |
|---|---|
| Is Pip OK / what's it doing | `GET /health/composite` |
| What can it safely do | `GET /health/degradation` |
| Battery truth | `GET /battery` |
| Ask the mind for one step | `POST /mind/step?zone=<zone>` |
| Set a mission | `POST /pip/goal` or a `set_goal` intent |
| Grant / revoke motion | `POST /movement/grant` · `POST /movement/revoke` |
| Go live / pause | `POST /pip/live?on=true|false` |
| One autonomy decision | `POST /pip/arbiter/tick?allow_movement=true` |
| Smart nav advice (no move) | `POST /nav/plan` |
| Go to the charger | `POST /tasks/return-home?goal=charger&allow_movement=true` |
| Remember this place | `POST /topo/observe?name=<place>` |
| Cruise (smooth roam) | `POST /pip/cruise?on=true` (or `?dry_run=true`) |
| What has it been doing | `GET /tasks/history` · `GET /life/diary` |
| Help requests from Pip | `GET /pip/interrupts?mark_delivered=true` |
| Calibration + readiness | `GET /calibration` |

**Golden loop to run Pip:** power on → `GET /calibration` until
`ready_for_supervised_drive` → grant motion → `POST /pip/live?on=true` →
poll `GET /health/composite`, set goals, answer `/pip/interrupts`, and let the
arbiter live. Keep the area clear and a hand near stop on the first runs.

— End of handover. Treat the safety floor as sacred; everything else is yours to direct.
