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
cleo-rover drive --linear 0.2 --duration-ms 250
cleo-rover stop
```

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
```

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
