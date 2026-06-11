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
POST /drive
POST /stop
POST /expression
POST /turret
GET  /sensors
```

## Hardware mode later

When the parts arrive, we will add concrete drivers for:

- Freenove motor board
- Waveshare 2-inch ST7789 screen
- Freenove 8MP camera stream
- USB mic/speaker routing

Until then, the API contract is stable and testable.
