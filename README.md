# Cleo Rover Mk1 Software

Body-control service for Cleo Rover Mk1.

The Raspberry Pi 4B is the current body controller for the stock Freenove chassis. Hermes/Cleo on the PC is the brain.

## Operating Pip

If you are the agent/operator running Pip, **start with [`handover.md`](handover.md)** —
the canonical operating manual: the architecture, the mind intent contract +
refusal rules, the movement/grant + safety model, the bring-up calibration, and
the day-to-day API. [`agent.md`](agent.md) is the **historical** pre-overhaul audit
kept for context; the doorway/vision/brain issues it raised have all been fixed
(see the upgrade notes below).

Pi-local safety stays authoritative throughout: movement grants, armed motors,
bounded chunks, scan-before-move, the ultrasonic/cliff/bumper reflex, and a turret
bearing guard. Hermes/Cleo provides high-level intent only; the Pi validates and
may refuse every movement intent locally.

## Autonomous embodied-agent upgrade (2026-06-25)

Pip evolved from a remote-controlled body into a dual-process embodied agent:
instinctive and safe on its own, thoughtful when it matters, and never dependent
on the cloud to stay safe. Full audit + design rationale (with research citations)
is in [`docs/HANDOVER_2026-06-25_PIP_AUTONOMY_AUDIT.md`](docs/HANDOVER_2026-06-25_PIP_AUTONOMY_AUDIT.md).

Architecture (three layers, Pi-local safety authoritative):

- **Reflex** (Pi, hard real-time): ultrasonic stop + 30ms watchdog, plus new
  optional **cliff (downward IR)** and **bumper** reflexes. Never vetoed.
- **Instinct** (Pi, always-on, offline-capable): the doorway/hallway navigator
  (`rover/navigation.py`), reactive explore, line-follow, memory-biased scanning.
- **Mind** (pluggable LLM, optional): `rover/mind.py` asks an OpenAI-compatible
  endpoint (Hermes by default, or Claude/any gateway) for ONE bounded intent; the
  Pi validates and may refuse it, falling back to the deterministic policy.

What changed:

- **Doorway "cuts off / turns away" bug fixed** — event-based reflex freshness
  (no more phantom recovery turns), scan-center as the clearance source of truth,
  a configurable reflex floor (`safety.reflex_hard_cm`, was a hardcoded 45cm
  dead-wall), and a real creep band + hysteresis. Pure, unit-tested logic.
- **Honest distance** — one motion model (`rover/odometry.py`) for cm↔pulse;
  move/stride report estimated (not pretended) travel and detect stalls; median
  ultrasonic filtering for scans.
- **Perception in the loop** — `rover/vision_service.py` emits real
  `vision_analysis` events (fixes `latest_vision: null`); vision is advisory and
  can add caution but never relax a reflex.
- **Voice** — `rover/voice_daemon.py`: offline wake-word → STT → `/pip/command`
  (`cleo-rover listen`, `/hearing/listen`). Talking never enables movement.
- **Explore + map + recall** — decaying landmark memory, pre-move memory consult,
  and `/tasks/return-to <landmark>` (e.g. the charger).
- **Soul** — unified emotion engine with an internal heartbeat so mood/energy/
  curiosity evolve on their own and actually drive behavior.

New endpoints: `/mind/status`, `/mind/step`, `/hearing/listen`,
`/autonomy/heartbeat`, `/tasks/line-follow`, `/tasks/return-to`. New CLI:
`cleo-rover listen | line-follow | return-to`, `cleo-rover-brain --use-mind`,
`cleo-rover-voice`. New config sections: `odometry`, `vision`, `mind`, `voice`,
`safety.reflex_hard_cm`/`cliff_reflex_enabled`/`bumper_reflex_enabled`,
`life_loop.heartbeat_seconds`. Optional extras: `pip install '.[vision]'` and
`'.[voice]'` (ARM-guarded; no-ops on dev hosts).

It also adds a **self-directed layer** (default-off): a behavior-arbitration loop
(`/pip/arbiter`) that picks what to do from mood/energy/curiosity/battery/goals/
people/time, auto self-preservation (low battery → return-to-charger), a goal/
mission layer the LLM mind can set (`/pip/goal`, `set_goal`), person/pet social
reactions, quiet-hours obedience, thermal back-off, and a stuck-escalation ladder.

## Tier 3: proprietary mapping & navigation (no LiDAR)

A body-frame "smart nav" brain built for our exact sensors (no LiDAR/encoders/IMU),
following the published cheap-robot playbook:

- **Rolling occupancy grid** (`rover/occupancy.py`) — robot-centric log-odds map
  with a sonar inverse sensor model (wide-FREE / narrow-OCCUPIED cone) + frontier
  detection. Self-heals as Pip drifts instead of smearing like a global map.
- **VFH+ steering** (`rover/vfh.py`) — polar-histogram obstacle avoidance from one
  sonar sweep with robot-width safety, hysteresis, and a goal/commitment cost.
  Drift-immune (body frame); fixes doorway oscillation properly.
- **Wall-following** (`rover/wall_follow.py`) — PD + corner handling; best coverage
  primitive without pose.
- **Optical-flow stall/looming** (`rover/vision_service.py`) — sparse Lucas-Kanade
  confirms "am I actually moving?" and flags looming the narrow sonar misses.
- **Topological place graph** (`rover/topo_map.py`) — places fingerprinted by a
  fused sonar+visual+IR signature, recognized by ≥2-of-3 voting so revisits reset
  drift; plan routes by name ("go to kitchen").
- **Memory consolidation** (`rover/consolidation.py`) — episodic sightings decay/
  reinforce/promote into durable facts ("the charger is in the office").

Endpoints (all sim-safe; movement still gated): `/nav/plan`, `/nav/grid`,
`/topo/observe`, `/topo/graph`, `/topo/plan`, `/memory/consolidate`, `/memory/facts`,
`/tasks/wall-follow`, `/vision/flow`. New config section `nav` (all flags default
**off**). All advisory — none can relax a reflex. Enable guide:
[`docs/HANDOVER_2026-06-25_PIP_TIER3_NAV_MAPPING.md`](docs/HANDOVER_2026-06-25_PIP_TIER3_NAV_MAPPING.md).

Everything is verifiable now in simulator + unit tests (`python -m pytest -q`,
365 passing). Only physical *calibration + deliberate enablement* is left for
supervised hardware runs — odometry coefficients (UMBmark), vision FPS/threshold,
USB-mic levels/wake-word, verifying IR/bumper polarity before enabling the cliff/
bumper reflexes, and turning on the arbiter. None are on the safety-critical path
(the reflexes and `validate_intent` are proven in sim first). Step-by-step:
[`docs/HANDOVER_2026-06-25_PIP_ENABLE_ON_HARDWARE.md`](docs/HANDOVER_2026-06-25_PIP_ENABLE_ON_HARDWARE.md).

## What works on the current Pi 4B rover

Runs fully in simulator + hardware-presence, and (after the bring-up calibration)
motor-armed modes. Implemented and tested (365 tests):

- **Safety floor (authoritative):** 30ms watchdog + 20ms drive-monitor + ultrasonic
  reflex + turret **bearing guard** + cliff/bumper reflexes (default-off) + movement
  grants + bounded motion budget + battery cutoff.
- **Navigation:** doorway/hallway navigator, reactive explore, line-follow, and the
  Tier-3 body-frame stack — rolling occupancy grid, VFH+ steering, wall-following,
  topological place-graph, frontier exploration, and continuous "cruise" motion.
- **Self-direction:** a behavior arbiter that picks what to do from mood/energy/
  curiosity/battery/people/time; goals the LLM mind can set; person/pet social
  reactions; quiet-hours obedience; thermal back-off; stuck-escalation.
- **Self-preservation:** honest sag-aware battery SOC → traverses the place-graph to
  the charger and docks when low; asks for help when it can't.
- **Perception:** on-Pi vision (TFLite) + optical-flow stall/looming → real
  `vision_analysis` events; advisory only, never relaxes a reflex.
- **Voice:** offline wake-word → STT → `/pip/command` (talking never moves the robot).
- **Memory:** SQLite events, decaying spatial memory, a topological graph, and
  consolidated semantic facts; survives reboots.
- **Expression (no display yet):** RGB-as-face affect + a truthful inner-life diary.
- **Observability:** one-call `GET /health/composite`, graceful-degradation tiers, a
  browser operator panel at `/`, and a bring-up `GET /calibration`.
- **Pluggable LLM mind:** `rover/mind.py` asks an OpenAI-compatible endpoint for one
  bounded, Pi-validated intent; the deterministic local policy is the default + fallback.
- Persistent SQLite state; personality/life-loop config; Cleo Hub awareness; the
  safety simulator; systemd unit templates; the PC-side `cleo-rover-brain` loop; a
  Cleo-native Freenove FNK0043 motor/servo map; `/config`; smoke tests.

The Waveshare ST7789 display driver/renderer exist in code, but the owner does not
own a display yet, so **RGB + voice are the live expression channels**.

## Run locally

```bash
cd ~/cleo-rover
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'        # on the Pi use '.[pi]' (+ optional '.[vision]'/'.[voice]')
uvicorn rover.service:app --host 127.0.0.1 --port 8099
```

Smoke test in another terminal:

```bash
python scripts/smoke_test.py
```

Render screen-expression previews:

```bash
python scripts/render_expressions.py
```

Open browser operator panel while the service is running:

```text
http://127.0.0.1:8099/
```

Use the operator CLI:

```bash
cleo-rover status
cleo-rover display-test
cleo-rover expression thinking --text booting
cleo-rover event wake_word --label Cleo
cleo-rover hear
cleo-rover snapshot
cleo-rover tick
cleo-rover autonomy
cleo-rover drive --linear 0.2 --duration-ms 250
cleo-rover stop
```

Run the PC-side autonomy brain loop:

```bash
cleo-rover-brain --once
cleo-rover-brain --interval 5
```

Movement requests remain disabled unless both are true:

1. the brain is started with `--allow-movement`; and
2. the body reports `motors_armed: true` from hardware config/readiness.

## API

The installed systemd service binds the API to `127.0.0.1:8099` by default. Use the local `cleo-rover` CLI or the Pi-local Telegram agent for operation; do not expose the rover control API on the LAN unless you deliberately add separate authentication and firewalling.

```text
GET  /health
GET  /status
GET  /config
GET  /doctor
GET  /preflight
GET  /sensors
POST /data/prune
GET  /last-seen
POST /drive
POST /stop
POST /expression
POST /turret
GET  /sensors
POST /events
GET  /events/recent
POST /heartbeat
GET  /autonomy/state
GET  /autonomy/dashboard
POST /autonomy/tick
GET  /cleo-hub
GET  /map
GET  /map/summary
GET  /situation
POST /map/remember
POST /safety/simulate
POST /hearing/simulate
POST /vision/snapshot
POST /vision/motion
POST /presence/look-around
POST /presence/remember-room
GET  /mind/status
POST /mind/step
POST /autonomy/heartbeat
POST /hearing/listen
POST /tasks/line-follow
POST /tasks/return-to
GET  /pip/arbiter
POST /pip/arbiter/tick
GET  /pip/goal
POST /pip/goal
DELETE /pip/goal
POST /nav/plan
GET  /nav/grid
POST /nav/grid/reset
POST /topo/observe
GET  /topo/graph
GET  /topo/plan
POST /topo/merge
POST /memory/consolidate
GET  /memory/facts
POST /vision/flow
POST /tasks/wall-follow
POST /pip/cruise
GET  /battery
GET  /calibration
GET  /pip/rgb-affect
POST /tasks/return-home
GET  /health/composite
GET  /health/degradation
GET  /tasks/history
POST /pip/live
GET  /life/diary
```

### One-call status

`GET /health/composite` is the single "is Pip OK / what is it doing / can it move
now?" view — battery SOC + health, mood/energy, movement permission (+ grant
owner), active goal, the arbiter's current choice, every subsystem readiness bit,
nav/place state, RGB affect, and the build/soul version, with a top-level
`ready_to_move` + `blockers`.

## Autonomy phases implemented

> **Note:** these early phases (A–F) document the original autonomy scaffold. They
> are all now superseded by the full implementation described above — voice, vision,
> mapping, and the LLM mind are real (not stubs). Kept here for lineage.

### Phase A: event model

The rover can now receive and retain recent stimulus events:

- sound
- speech
- wake word
- motion
- camera snapshot
- button
- bump/obstacle
- battery
- network
- manual control
- idle tick

### Phase B: Cleo body state engine

The autonomy engine maintains:

- mood
- attention
- curiosity
- energy
- confidence
- connection state
- current intent
- last stimulus and last behavior

### Phase C: safe behavior library

Implemented behaviors:

- `wake_response`
- `react_to_sound`
- `safety_stop`
- `curious_scan`
- `request_charge`
- `idle_presence`
- `show_disconnected`
- `hold`

### Phase D: voice/hearing hooks

`/hearing/simulate` creates synthetic events for testing; the **real** offline
voice path (wake-word → STT → `/pip/command`, via `rover/voice_daemon.py` and
`/hearing/listen`) is now implemented.

### Phase E: vision hooks

`/vision/snapshot` creates camera/motion events; **real** on-Pi vision
(`rover/vision_service.py`, TFLite + optical flow) now emits `vision_analysis`
events into the loop, with external/Hermes vision also supported via `/vision/analysis`.

### Spatial memory / mapping scaffold

There are still no encoders/IMU/LiDAR (distances are open-loop guesses), but Pip now
has a real body-frame mapping/nav stack (rolling occupancy grid + a topological
place-graph + consolidated facts) on top of the named-landmark memory:

```bash
curl -X POST http://127.0.0.1:8099/map/remember \
  -H 'content-type: application/json' \
  -d '{"id":"charger-dock","label":"Charging dock","kind":"dock","zone":"office","confidence":0.7}'
```

This stores observations in SQLite with zone, bearing, distance, confidence, notes, timestamps, and observation counts. After hardware arrives, camera/vision and odometry can update this into a simple topological room map.

### Phase F: limited movement autonomy

Autonomy can request tiny movement, but the body refuses real movement unless movement is explicitly allowed and motors are armed. The default config remains bench-safe.

## Hardware status

Current verified bench state:

- Raspberry Pi 4 boots from the Freenove car board through the GPIO/header when the 18650 battery pack is installed; USB-C power is not needed during car-board operation.
- I2C/SPI are enabled on the Pi.
- Freenove board I2C scan shows `0x40` for PCA9685 motor/servo PWM, `0x48` for the board ADC/power-sense device, and `0x70` for the PCA9685 all-call address.
- Pan/tilt servo channels `8/9` centered correctly at `1500us`.
- Motor channel mapping is verified against the physical wheels. Low-power hardware mode drives all four wheels forward/back smoothly and can turn left/right.
- First safe hardware config used `max_duty_cycle: 0.18`, `max_drive_duration_ms: 500`, and wheels lifted for initial testing.

## Hardware config

Default hardware assumptions live in:

```text
config/rover.default.json
```

Override them without editing code:

```bash
CLEO_ROVER_CONFIG=/path/to/rover.local.json uvicorn rover.service:app --host 0.0.0.0 --port 8099
```

The default profile is bench-safe:

- `bench_safe_no_motors: true`
- motors report unarmed
- drive commands still exercise the API and timeout logic
- `/sensors` exposes the display, motor, turret, Freenove channel map, and safety map

### Freenove stock-board map

We do **not** run Freenove's robot app/TCP server for Cleo Rover. The vendor repo is used only as a hardware reference. Cleo Rover now has its own native driver map in `rover/freenove.py`:

- PCA9685 I2C address: `0x40`
- PWM frequency: `50 Hz`
- left upper motor: PCA9685 channels `0/1`
- left lower motor: channels `3/2`
- right upper motor: channels `6/7`
- right lower motor: channels `4/5`
- pan/tilt servos: channels `8/9`
- line sensors BCM pins: `14/15/23`
- ultrasonic BCM pins: trigger `27`, echo `22`
- Waveshare 2-inch ST7789V display over SPI1 because the Freenove connection board occupies the first 20 physical pins: DIN/MOSI `20`, CLK/SCLK `21`, manual CS `6`, DC `25`, RST `5`, BL wired to `3.3V`/module power by default (`backlight_pin: null`)

The default max duty cycle is conservative at `0.35`, and real motor output stays disabled until a local config explicitly sets `bench_safe_no_motors: false` and the chassis is lifted for first movement tests.

## Safe setup checklist

For a fresh Pi or after pulling new code (the full, ordered bring-up + calibration
is in [`docs/HANDOVER_2026-06-25_PIP_FNK0043_AUDIT_AND_BRINGUP.md`](docs/HANDOVER_2026-06-25_PIP_FNK0043_AUDIT_AND_BRINGUP.md);
`GET /calibration` returns the same checklist + a `ready_for_supervised_drive` gate):

1. Boot Raspberry Pi OS Lite on the Pi 4B and verify SSH.
2. Enable I2C, SPI, camera interfaces (the ST7789 SPI1 step only if a display is wired).
3. Install/update the repo and run `pip install -e '.[pi]'` inside the project venv
   (add `'.[vision]'` / `'.[voice]'` for the camera/voice extras).
4. Install the main service with `sudo scripts/install_systemd.sh`.
5. `i2cdetect -y 1` → confirm `0x40` (PCA9685) and `0x48` (ADS7830); **set
   `sensors.pcb_version` (1 or 2)** for your board — a wrong value misreads the battery ~33%.
6. `GET /calibration` and complete the checklist: verify pan goes **right** on +pan,
   set IR polarity (`safety.line_drop_value`), measure coast distance, calibrate odometry.
7. Verify `/health/composite`, `/status`, `/config`, `/sensors`, `/preflight` before any floor movement.
8. Install the Telegram agent and profile-switch sudoers helper only after local service checks pass.
9. Enable reflexes/motion flags **last**, and use floor-cautious mode only for deliberate
   floor tests with a clear area and an armed, supervised movement grant.

## Hybrid body/brain control

Cleo Rover now uses a hybrid control contract for supervised autonomy:

- Pi body agent: local safety, estop, sensors, camera, RGB/screen moods, turret, and tiny movement execution.
- PC/Hermes brain: higher-level perception/planning that sends only high-level intents.
- The Pi validates every intent and may refuse movement if local safety is unhappy.

Useful local checks:

```bash
cleo-rover supervisor-status
cleo-rover body-intent mood --mood focused --speech "ready"
cleo-rover-brain --supervised-body --zone office --once
```

## Hardware mode operating rule

Normal powered-on operation should use the no-motor presence profile:

```bash
sudo scripts/set_rover_profile.sh presence
```

Only switch to the floor-cautious motor profile after the rover is on the floor, the area is clear, and movement is intentionally armed:

```bash
sudo scripts/set_rover_profile.sh floor-cautious
```

The stock Freenove motor/servo board has a Cleo-native driver. Motor output must remain gated by profile safety, movement grants, short command durations, and front-distance checks.
