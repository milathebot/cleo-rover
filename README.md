# Cleo Rover Mk1 Software

Body-control service for Cleo Rover Mk1.

The Raspberry Pi 4B is the current body controller for the stock Freenove chassis. Hermes/Cleo on the PC is the brain.

## What works on the current Pi 4B rover

This repo runs in safe simulator and hardware-presence modes:

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
- custom Cleo-native Freenove FNK0043 motor/servo map derived from the vendor codebase
- `/config` endpoint for pin/driver readiness
- smoke tests

## Run locally

```bash
cd /home/wiffl/cleo-rover
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
GET  /map/summary
GET  /situation
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

The default max duty cycle is conservative at `0.35`, and real motor output stays disabled until a local config explicitly sets `bench_safe_no_motors: false` and the chassis is lifted for first movement tests.

## Safe setup checklist

For a fresh Pi or after pulling new code:

1. Boot Raspberry Pi OS Lite on the Pi 4B and verify SSH.
2. Enable I2C, SPI, and camera interfaces.
3. Install/update the repo in `/home/cleo/cleo-rover` and run `pip install -e '.[pi]'` inside the project venv.
4. Install the main service with `sudo scripts/install_systemd.sh`.
5. Put the service into no-motor presence mode with `sudo scripts/set_rover_profile.sh presence`.
6. Verify `/health`, `/status`, `/config`, `/sensors`, and `/vision/snapshot` before any floor movement.
7. Install the Telegram agent and profile-switch sudoers helper only after local service checks pass.
8. Use floor-cautious mode only for deliberate floor tests with a clear area and an active movement arm.

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
