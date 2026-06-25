> ⚠️ **HISTORICAL session handoff.** Point-in-time notes from before the
> embodied-agent overhaul; the doorway/hallway behavior described here has since been
> rewritten and fixed. Current state: [`../handover.md`](../handover.md) + [`../README.md`](../README.md).

# Pip Rover handover: hallway scout + adaptive movement

Date: 2026-06-25
Repo: `milathebot/cleo-rover`
Branch: `master`
Latest commit at handover: `335900e Tune doorway scout scan behavior`

## Session goal

Bring Pip from cautious floor movement into a supervised hallway/office-doorway scout that can:

- keep ultrasonic safety online at all times
- speak during actions through ElevenLabs
- scan before moving
- move farther in open space and slow down near doorways
- avoid turret shell clipping during scans
- fail closed when sensors, vision, or movement permission are unhealthy

## Major changes made

### Safety and ultrasonic reliability

- Reused a singleton `gpiozero.DistanceSensor` for the HC-SR04 ultrasonic path so watchdog, preflight, sensors, and scout calls do not fight over GPIO22/27.
- Treated impossible negative ultrasonic readings as `unknown` at the hardware/service level.
- Hardened range scans so negative samples are ignored instead of being saved as invalid spatial memory.
- Ensured map/visual scans recenter the turret in `finally` paths after errors.
- Hallway scout now returns safe JSON on internal errors instead of raw HTTP 500.

### TTS and action narration

- Restored ElevenLabs MP3 playback gain support via `CLEO_ROVER_MPG123_GAIN`.
- Added action narration for hallway scout when `--speak` is used:
  - scout start
  - path open / planned movement
  - doorway close / cautious creep
  - side opening / turn
  - completion
- Extended CLI timeout for spoken hallway scout runs.
- Extended/renewed movement grants while TTS is speaking so narration does not expire the movement window mid-task.

### Adaptive movement

- Added adaptive route-level stride selection:
  - large planned strides in open space
  - small creep steps near doorway/obstacles
  - sensor checks between chunks
- Fixed the core hallway-scout undertravel bug: adaptive stride was previously stopping after `0.15s`, cutting calibrated `570-850ms` chunks into tiny nudges. It now waits for the actual drive duration plus a small buffer before stopping/checking.
- Calibrated floor movement from the initial undertravel:
  - forward linear: `0.34` -> `0.38`
  - duration scale: `55ms/cm` -> `95ms/cm`
  - floor cautious `max_drive_duration_ms`: `450` -> `850`
  - floor cautious `default_drive_duration_ms`: `220` -> `300`
- Increased allowable adaptive stride/chunk bounds:
  - `max_step_cm` can go up to `90`
  - `stride_chunk_cm` can go up to `16`

### Doorway behavior

- Reduced default hallway scan angles from physical extremes:
  - old: `-70,-45,-25,0,25,45,70`
  - new: `-60,-40,-20,0,20,40,60`
- Added `--scan-angles` CLI override for hallway scout.
- Added `doorway-creep` behavior:
  - if center is below `clear_cm` but still safely above `blocked_cm + 10`, and no side bearing is clearly better, Pip creeps forward instead of endless scan-turning.

## Commits from this session

Most recent first:

- `335900e Tune doorway scout scan behavior`
- `c5ee99f Let adaptive stride chunks complete`
- `48e6f95 Increase Pip hallway stride limits`
- `c353273 Calibrate Pip floor forward movement`
- `faf0c12 Treat invalid ultrasonic ranges as unknown`
- `59f3a07 Keep hallway scout movement grant alive during speech`
- `bc44edb Extend hallway scout client timeout for speech`
- `7ad5adf Restore Pip TTS gain and action speech`
- `b1b5513 Add adaptive Pip hallway strides`
- `ba6be06 Harden hallway range scan readings`
- `7fccd26 Return hallway scout errors safely`
- `a5a1d9f Reuse ultrasonic sensor across safety checks`
- earlier in the run: `a93c65c Make hallway scout scan before forward steps`

## Known good hardware/profile state

Pi profile should be `hardware-floor-cautious`.

Important status values after latest updates:

```json
"motors_armed": true,
"stopped": true,
"safety": {
  "max_drive_duration_ms": 850,
  "default_drive_duration_ms": 300,
  "front_stop_distance_cm": 30.0
}
```

ElevenLabs TTS expected service env includes:

```ini
ALSA_CARD=3
CLEO_ROVER_MPG123_GAIN=166666
CLEO_ROVER_ELEVENLABS_API_KEY=...
CLEO_ROVER_ELEVENLABS_VOICE_ID=...
CLEO_ROVER_ELEVENLABS_MODEL_ID=eleven_multilingual_v2
CLEO_ROVER_ELEVENLABS_OUTPUT_FORMAT=mp3_44100_128
HERMES_PIP_SPEAK_RESPONSE=true
```

Do not commit secrets. TTS config lives in the Pi systemd override, e.g. `/etc/systemd/system/cleo-rover.service.d/zz-tts.conf`.

## Shutdown state

The session ended because the battery was getting low. Recommended shutdown sequence was:

```bash
cleo-rover stop
cleo-rover turret --pan-deg 0
sudo systemctl stop cleo-rover.service
sudo shutdown -h now
```

Recharge before next floor movement session.

## Next startup checklist

On the Pi:

```bash
cd ~/cleo-rover
sudo systemctl start cleo-rover.service
sleep 3
cleo-rover status
cleo-rover sensors
cleo-rover preflight --mode floor-cautious
```

If updating from GitHub:

```bash
cd ~/cleo-rover
cleo-rover stop
git fetch origin
git reset --hard origin/master
. .venv/bin/activate
pip install -e '.[pi]'
sudo systemctl restart cleo-rover.service
sleep 3
sudo scripts/set_rover_profile.sh floor-cautious
sleep 2
cleo-rover status
cleo-rover preflight --mode floor-cautious
```

Confirm `max_drive_duration_ms` is `850` before running hallway scout.

## Recommended next test

First run a short, verbose doorway test:

```bash
cleo-rover turret --pan-deg 0
sleep 1
cleo-rover preflight --mode floor-cautious

cleo-rover hallway-scout \
  --zone office-doorway \
  --allow-movement \
  --cycles 6 \
  --vision-every 1 \
  --min-step-cm 4 \
  --max-step-cm 36 \
  --stride-chunk-cm 10 \
  --clear-cm 75 \
  --blocked-cm 45 \
  --pause-seconds 0.5 \
  --speak \
  --verbose
```

Look for:

- `adaptive-move` with chunks that physically complete, not tiny nudges
- `doorway-creep` when close but passable
- turret scan angles within `±60` unless overridden
- no `front_distance_cm` negative values
- no `GPIOPinInUse`

If shell clipping still appears, use narrower scan angles:

```bash
--scan-angles=-55,-35,-15,0,15,35,55
```

## Suggested staged adventure after a good doorway test

Stage 1, leave office doorway:

```bash
cleo-rover hallway-scout --zone office-doorway --allow-movement --cycles 10 --vision-every 1 --min-step-cm 4 --max-step-cm 36 --stride-chunk-cm 10 --clear-cm 75 --blocked-cm 45 --pause-seconds 0.5 --speak
```

Stage 2, manually bias right turn once near/outside the doorway:

```bash
cleo-rover movement-grant hallway-right-turn --allow-movement --duration-seconds 15 --max-linear 0.40 --max-turn 0.75
cleo-rover rotate-step --deg 25
sleep 1
cleo-rover stop
```

Stage 3, down hallway:

```bash
cleo-rover hallway-scout --zone hallway-right --allow-movement --cycles 6 --vision-every 2 --min-step-cm 5 --max-step-cm 48 --stride-chunk-cm 12 --clear-cm 80 --blocked-cm 45 --pause-seconds 0.5 --speak
```

Stage 4, approach next room:

```bash
cleo-rover hallway-scout --zone next-room-entry --allow-movement --cycles 4 --vision-every 1 --min-step-cm 3 --max-step-cm 24 --stride-chunk-cm 8 --clear-cm 70 --blocked-cm 45 --pause-seconds 0.5 --speak
```

## Open issues / next improvements

- True semantic vision is still represented as a placeholder in hallway scout output unless Hermes/cloud vision bridge is actively available and wired into the task. Continue improving “talking to Hermes” / vision analysis integration.
- A single front ultrasonic can miss angled side/corner collisions. Add a bumper switch, side ToF sensors, or a physical contact sensor for robust doorway traversal.
- Doorway routing is still reactive, not a map-based path planner. Next step is a higher-level route command such as `office-to-next-room` with explicit phases: doorway exit -> right turn -> hallway traverse -> next-room entry.
- Battery was low at session end; recharge before more movement tests.
