# Handover: enabling Pip's autonomy on the real hardware

This is the supervised checklist for the agent/operator who runs Pip on the Pi
after merging the `feat/autonomous-embodied-agent` branch. Everything in the
branch is verified in simulator + unit tests (`python -m pytest -q`, 365 passing as of the latest pass).
What remains is **physical calibration and deliberate enablement** — none of it is
on the safety-critical path (the reflex floor and `validate_intent` are proven in
sim first), but several steps **must be done supervised, in this order**.

Golden rules (unchanged): Pi-local safety is authoritative; nothing (vision, the
LLM mind, voice) can relax a reflex; movement needs a grant **and** armed motors;
start every floor session with the area clear and a finger on stop.

---

## 0. Install

```bash
cd ~/cleo-rover            # the repo on the Pi
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[pi]'                 # core + GPIO/SPI/I2C
pip install -e '.[vision]'             # optional: on-Pi camera detector (TFLite)
pip install -e '.[voice]'              # optional: offline voice (sounddevice + wakeword)
sudo scripts/enable_spi1_display.sh && sudo reboot   # if the display is wired
```

Verify the service boots in sim, then in hardware-presence (no motors):

```bash
python -m pytest -q
CLEO_ROVER_MODE=sim uvicorn rover.service:app --port 8099   # then: cleo-rover status
CLEO_ROVER_CONFIG=config/rover.hardware.presence.json CLEO_ROVER_MODE=hardware \
  uvicorn rover.service:app --port 8099
cleo-rover preflight --mode presence
```

---

## 1. Verify every sensor (before any movement)

```bash
cleo-rover sensors      # check: ultrasonic_ready, line_sensors, bumpers, battery_percent, camera.ready
cleo-rover doctor       # cpu_temp_c, memory, disk, tool availability
```

You should see real `line_sensors` (3 values), `bumpers` (if wired), a plausible
`battery_percent`, and `ultrasonic_ready: true`.

## 2. ⚠️ Verify IR + bumper polarity, THEN enable the cliff/bumper reflexes

These ship **OFF** because the "no-floor" digital value is hardware-specific and a
wrong polarity either false-stops on a dark line or — worse — trusts an unverified
guard. The body service will log a warning if a motor-armed profile has the cliff
reflex disabled.

1. Hold Pip (wheels off the floor). Run `cleo-rover sensors` repeatedly while you
   pass a hand / move it over a **table edge or stair lip**.
2. Note the `line_sensors` value when **all three see "no floor"** (the drop). That
   number is your `line_drop_value` (often `1`, but verify).
3. Confirm it is **different** from the value the sensors read while centered on a
   line you'd want to follow (else a fat line reads as a cliff).
4. In `config/rover.hardware.floor.cautious.json` → `safety`, set:
   `"line_drop_value": <verified>`, `"cliff_reflex_enabled": true`,
   `"bumper_reflex_enabled": true`.
5. Re-test on a **real edge, wheels lifted**, with movement armed but Pip held:
   confirm `cleo-rover sensors` shows `last_reflex_stop.kind == "cliff"` at the edge.

## 3. Calibrate open-loop odometry (there are no encoders)

Distances are calibrated guesses. Tune `config` → `odometry`:

1. Lift wheels; arm floor-cautious; `cleo-rover move-step --forward-cm 10` and time
   a few pulses on the floor with a tape measure.
2. Adjust `odometry.cm_s_per_duty` / `duty_deadband` until `estimated_cm` in the
   move-step response roughly matches measured travel at the floor duty (~0.38).
3. For turns, run a UMBmark-style square (CW then CCW) and trim
   `odometry.deg_s_per_turn_duty`. Heading error is unbounded without an IMU —
   keep moves short and re-scan often. Treat all distances as guesses.

## 4. Point the mind at Hermes (or Claude)

The LLM mind is OpenAI-compatible and optional (Pip works fully offline without it).

```bash
export HERMES_API_BASE=http://<hermes-host>:<port>/v1
export HERMES_API_KEY=...            # if required
export HERMES_MODEL=hermes-agent
# or point at any OpenAI-compatible gateway via MIND_API_BASE/MIND_API_KEY/MIND_MODEL
cleo-rover-brain --use-mind --once   # one validated deliberative step
```

The Pi validates every intent and falls back to the deterministic policy on
timeout/garbage/offline. Confirm `cleo-rover` GET `/mind/status` shows `configured: true`.

## 5. Offline voice (talk to Pip)

```bash
# pick ONE offline STT backend:
#  a) whisper.cpp: build it, then
export CLEO_ROVER_WHISPER_BIN=/path/to/whisper-cli
export CLEO_ROVER_WHISPER_MODEL=/path/to/ggml-tiny.en.bin
#  b) vosk: pip install vosk + a model dir
export CLEO_ROVER_VOSK_MODEL=/path/to/vosk-model-small-en
cleo-rover-voice --backends            # confirm a backend is available
cleo-rover-voice --once                # say something; it routes to /pip/command
```

Tune the USB mic with `ALSA_CARD` / `voice.mic_device`. Install the systemd unit
(`deploy/systemd/cleo-rover-senses.service`, which now runs `cleo-rover-voice`).
Talking never enables movement.

## 6. On-Pi vision (optional)

Install `.[vision]`, drop a quantized INT8 SSD-MobileNet TFLite model + labelmap
on the Pi, and set `config` → `vision.model_path` / `vision.labelmap_path`. Without
a model it degrades to a low-confidence placeholder (the pipeline still runs). Keep
active cooling on; detection runs ~5 Hz on a Pi 4. Vision is advisory only.

## 7. Teach Pip its charger (so self-preservation works)

```bash
cleo-rover map-scan --zone office          # build some spatial memory
curl -X POST localhost:8099/map/remember -H 'content-type: application/json' \
  -d '{"id":"charger-dock","label":"Charging dock","kind":"dock","zone":"office","bearing_deg":0,"distance_m":1.0,"confidence":0.8}'
cleo-rover return-to charger               # confirm it orients toward the dock
```

## 8. Go self-directed (the arbiter) — supervised first

Only after 1–7 pass on the floor:

1. `config` → `life_loop`: `"arbiter_enabled": true` (and tune
   `arbiter_interval_seconds`, `return_to_charger_min_battery`). The arbiter loop
   auto-starts **only on hardware** with the flag on.
2. First runs **supervised, clear area, hand on stop**. Watch
   `cleo-rover` GET `/pip/arbiter` and the event log; verify it returns to the
   charger when battery drops and respects quiet hours.
3. Drive it manually anytime with `POST /pip/arbiter/tick?allow_movement=true`.

---

## Verification sequence (every code pull)

```bash
python -m pytest -q                                  # 365 passing
CLEO_ROVER_MODE=sim uvicorn rover.service:app --port 8099 &
python scripts/smoke_test.py                         # drive-timeout safety, sensors
cleo-rover preflight --mode floor-cautious           # only on the floor, area clear
```

## Known follow-ups (tracked, not blockers)

- **Tier 2C** — per-task ownership of the movement grant (a naive lock deadlocks
  the nested motion tasks; the desync cannot breach the safety floor).
- Deeper coverage-driven heading selection, wall-following, optical-flow stall
  confirmation, topological room graph, memory consolidation (Tier 3 in the audit).
- Migrate FastAPI `on_event` to lifespan handlers (deprecation warnings only).
