# Cleo Rover Mk1 Software

Body-control service for Cleo Rover Mk1.

The Pi Zero 2 W is the body controller. Hermes/Cleo on the PC is the brain.

## What works before hardware arrives

This repo runs in `sim` mode now:

- health/status API
- drive commands with automatic timeout safety
- stop command
- expression state for the 2-inch screen
- PNG expression renderer for the Waveshare 2-inch screen
- PC-side operator CLI
- persistent SQLite autonomy state, events, cooldowns, and spatial memory
- personality/life-loop config for curiosity, attention-seeking, quiet hours, and behavior cooldowns
- Cleo Hub awareness for focus/quiet-mode context
- browser autonomy dashboard at `/autonomy/dashboard`
- safety simulator for obstacle, bump, low-battery, and disconnect scenarios
- arrival-day calibration wizard scaffold
- senses daemon stub for future mic/camera event streaming
- systemd unit templates for Pi body, Pi senses, and PC brain services
- PC-side `cleo-rover-brain` autonomy loop
- event model for sound/speech/wake/motion/bump/battery/network stimuli
- autonomy state engine: mood, attention, curiosity, energy, confidence
- safe behavior decisions for wake response, sound reaction, safety stop, curiosity scan, charge request, idle presence
- hearing and vision simulation hooks for pre-hardware testing
- camera/speaker/mic placeholders
- config-driven hardware map and safety limits
- `/config` endpoint for pin/driver readiness
- smoke tests

## Run locally

```bash
cd /home/wiffl/projects/cleo-rover
python3 -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
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

```text
GET  /health
GET  /status
GET  /config
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
POST /map/remember
POST /safety/simulate
POST /hearing/simulate
POST /vision/snapshot
```

## Autonomy phases implemented

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

`/hearing/simulate` creates sound/speech/wake events now. Real mic/audio routing will replace this after the USB mic is validated.

### Phase E: vision hooks

`/vision/snapshot` creates camera/motion events and returns an analysis stub. Real camera frames will route to Hermes/vision later.

### Spatial memory / mapping scaffold

Mk1 cannot do true SLAM before the camera, IMU, and motor odometry are wired, but it can now remember named landmarks and places:

```bash
curl -X POST http://127.0.0.1:8099/map/remember \
  -H 'content-type: application/json' \
  -d '{"id":"charger-dock","label":"Charging dock","kind":"dock","zone":"office","confidence":0.7}'
```

This stores observations in SQLite with zone, bearing, distance, confidence, notes, timestamps, and observation counts. After hardware arrives, camera/vision and odometry can update this into a simple topological room map.

### Phase F: limited movement autonomy

Autonomy can request tiny movement, but the body refuses real movement unless movement is explicitly allowed and motors are armed. The default config remains bench-safe.

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
- `/sensors` exposes the display, motor, turret, and safety map

## Arrival-day checklist

When parts arrive:

1. Photograph all labels, boards, included cables, and motor-driver markings.
2. Confirm the power bank has enough outputs/current for Pi + motor/servo rail.
3. Boot Pi OS Lite, enable SSH, SPI, I2C, and camera.
4. Run `scripts/pi_setup.sh` on the Pi.
5. Start in sim/bench-safe mode first. Do not arm motors yet.
6. Test `/health`, `/status`, `/config`, and `/expression/preview.png`.
7. Wire and test the display alone.
8. Wire and test one motor side with wheels lifted.
9. Only then enable motor arming in a local config.

## Hardware mode later

When the parts arrive, we will add concrete drivers for:

- Freenove motor board
- Waveshare 2-inch ST7789 screen
- Freenove 8MP camera stream
- USB mic/speaker routing

Until then, the API contract is stable and testable.
