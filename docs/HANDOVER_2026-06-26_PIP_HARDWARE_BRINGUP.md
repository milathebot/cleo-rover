# Handover — 2026-06-26 — Pip hardware bring-up: calibration, voice, camera, first errand

Live, hands-on session on the physical robot (Pi 4B, FNK0043) over SSH with the owner
present. Outcome: Pip was powered up on freshly charged 18650s, calibrated, given
working speech-to-text + a live camera feed, and **teleoperated down the hallway into
another room to greet someone** — its first real point-to-point errand.

## What was calibrated / configured on the robot (persisted, per-robot local)
Lives in `config/rover.hardware.local.json` (gitignored) and the SQLite KV store:

- **Odometry calibrated** (`/calibrate/odometry`, persisted in KV `odometry_calibration`):
  `cm_s_per_duty = 48.32` (was 33.0 — forward under-counted ~46%), `deg_s_per_turn_duty = 185.19`.
  Measured: 0.4 duty / 2000 ms → 30 cm; 1.0 turn / 600 ms → 90°. Note: pure in-place
  turns run at the `min_inplace_turn` floor (effective turn = 1.0).
- **`voice.mic_device = "Device"`** — the USB mic is ALSA capture card `Device`
  ("USB PnP Sound Device"); the **speaker is `UACDemoV10`** (playback). Separate cards.
- **`safety.range_hold_ms = 700`** (was 250) — the HC-SR04 drops pings under motor
  noise while driving; the larger hold window lets the forward reflex ride through the
  blind windows on the last good reading instead of false-stopping (`range_unknown`).
- Carried over from prior bring-up: `turret.pan_trim_deg = -16`, `motors.min_inplace_turn = 1.0`,
  `safety.cliff_reflex_enabled = true`, `safety.line_drop_value = 1`, `bench_safe_no_motors = false`.
- **Boot-safe**: `life_loop.arbiter_enabled = false` and `quiet_hours.enabled = true`
  (restored at end of session) — Pip will not self-drive on boot.

## Audio / voice status
- **STT works**: `faster-whisper` installed (ctranslate2 + onnxruntime cp313 wheels exist).
  `base.en` int8 loads ~19 s; `/voice/status` → `stt_ready: true`, `mic.ready: true`.
  `/hearing/listen` capture→transcribe verified end-to-end.
- **Wake word ("Hey Pip") BLOCKED on Python 3.13**: `openwakeword` hard-requires
  `tflite-runtime`, which has **no cp313/aarch64 wheel** (also no `webrtcvad` cp313 wheel).
  So no hands-free always-on wake word yet. The always-on `cleo-rover-voice` systemd unit
  was **not** installed (it would fail without openwakeword). STT/`/hearing/listen` work
  when triggered.
  - Fix paths (next session): (1) run the voice daemon from a separate **Python 3.11**
    venv (Bookworm ships 3.11; tflite-runtime aarch64 wheels exist) → full openWakeWord +
    a trained "Hey Pip" model; (2) Porcupine (`pvporcupine`, cp313 wheel, own engine,
    free AccessKey) with a small `voice_daemon` code path.
- **Volume** lowered 25% on the owner's request: PCM `72% → 54%` (−13.6 dB), `alsactl store`d.
- `/speech/say?text=...` makes Pip speak an exact line (direct TTS, no Hermes). Surfaced on
  the dashboard as a **👋 Say hi** button and a `say <text>` prefix in the Talk-to-Pip box.

## Software fixes shipped this session (all on master)
- `fix(nav)`: reactive-explore loop falls back to a **median** front read when a single
  ping is None, so Pip commits to forward crawls instead of scan→turn forever; floor
  preflight accepts `hardware-floor-cautious*` (the `-local` suffix) and uses the median
  fallback for the ultrasonic/front-clear checks.
- `tune(nav)`: bolder roam — crawl when ≥ 85 cm clear (was 130).
- `feat(turret)`: **pan slew-rate-limit** — the servo eases to scan angles instead of
  snapping (a hard jump had vibrated the pan-mount nut loose). `turret.pan_slew_deg` /
  `pan_slew_settle_ms` (12°/15 ms default); 0 = old snap.
- `feat(console)`: **live MJPEG camera feed** (`GET /camera/stream.mjpg`, rpicam-vid, async
  subprocess, exclusive single-viewer) + a Camera panel toggle → enables **teleop** (drive
  Pip into another room watching the feed). One-tap "Say hi" + `say <text>`.
- `fix(console)`: manual forward/back were too weak to move (linear 0.22 buzzes on the 4WD);
  bumped to 0.4 / 600 ms. Turns were already fine (boosted to full duty by `min_inplace_turn`).

## How to drive Pip room-to-room TODAY (teleop)
There is no autonomous "go to room X" yet (no encoders/IMU/LiDAR; open-loop odometry drifts;
it can't find an unmapped doorway). The reliable way:
1. Open the dashboard on a phone/laptop you carry (or your desk): `http://<pi>:8099/`.
2. Camera panel → **📷 start** (live feed; exclusive — one viewer).
3. **⚠ manual drive** → ▲ fwd / ◄ ► turn, watching the feed. Reflexes (obstacle/cliff/
   watchdog) stay active; the baby gate keeps the stairs safe.
4. At the destination, tap **👋 Hi** or type `say <line>`.

## Known issues / next steps
- **HC-SR04 dropouts under motion** (electrical noise / vibration). Mitigated by
  `range_hold_ms = 700`; root-cause fixes are hardware (shielded/twisted echo lead,
  separate sensor power, firmer mount). The front wire is also a bit fragile — it read 0.0
  after the turret reattach until the **board-end** connector was reseated.
- **Slight left veer** on straight drives (4WD motor mismatch). No straight-line trim exists
  in `MotorConfig` yet — add a per-side duty bias.
- **Wake word** — needs the py3.11 venv or Porcupine path above.
- **Real autonomous navigation** (room-to-room, self-docking) needs the shopping-list
  hardware: wheel encoders + IMU (BNO055) first, then a 2D LiDAR. See the project memory.
- Pre-existing test brittleness: `tests/test_api.py::test_first_adventure_observe_only_wrapper_and_router`
  fails on the Pi only (presence preflight blocks when motors are armed → response omits the
  `safety` key the test asserts). Not from this session's changes; fix the test to handle the
  blocked path.

## State at shutdown
Quiet hours restored (on), arbiter disabled (boot-safe), all calibration/config persisted,
services stopped cleanly, Pi halted. On next power-up the body service auto-starts boot-safe;
`git pull` for the latest, then teleop via the dashboard camera as above.
