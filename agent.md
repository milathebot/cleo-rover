> ⚠️ **HISTORICAL (superseded).** This is the *pre-overhaul* audit that motivated the
> embodied-agent rebuild. **Every issue it raises has since been fixed** — stale
> reflex handling, raw-front-vs-scan-center, doorway hysteresis/state, `latest_vision:
> null`, and brain-not-in-the-loop are all resolved. Do **not** treat the
> "suspected issues / questions to audit" below as current. For the current system,
> read **[`handover.md`](handover.md)** (operating manual) and [`README.md`](README.md).
> Kept here only as a record of the original problem statement.

# Agent audit handover: Pip hallway scout and brain connectivity

Date: 2026-06-25
Repo: `milathebot/cleo-rover`
Branch at handover: `master`
Latest local/remote commit when this was written: `25b333b Add Pip hallway scout handover`

This document is for Codex, Claude, or any repo-audit agent before making code changes. Please audit the current architecture and propose improvements first. Do not immediately patch movement code without understanding the safety model and the latest real hardware run.

## Context

Pip is a Raspberry Pi 4B/Freenove FNK0043 rover with:

- Pi-local FastAPI body service in `rover/service.py`
- CLI in `rover/client.py`
- Freenove motor/servo/ultrasonic/display integrations in `rover/drivers.py`, `rover/freenove.py`, and `rover/peripherals.py`
- persistent event/spatial memory in SQLite
- `pip-brain` digest in `rover/pip_brain.py`
- `pip-soul` identity protocol in `rover/pip_soul.py`
- Hermes/Cleo intended as high-level brain, not hard real-time motor controller

The current physical focus is supervised office-doorway/hallway autonomy. Pip starts in the office, tries to approach/exit the doorway, and should eventually turn into the hallway. Safety must remain Pi-local: short bounded moves, stop after chunks, range scans before movement, movement grants, and reflex stop.

## Important safety rules for auditors

- Do not remove Pi-local reflex stop or movement grants.
- Do not make Hermes/cloud/model calls responsible for emergency braking.
- Do not issue real movement commands from this audit unless explicitly supervised by the operator.
- Prefer simulator/tests and code review first.
- Hardware profile for movement is `floor-cautious`; normal presence mode should not move motors.
- Battery below about 50% means gentle tests only; below 30% should charge before movement.
- A single front ultrasonic can miss side/corner doorway collisions. Any autonomous doorway strategy must remain conservative.

## Latest real run summary

User ran:

```bash
cleo-rover hallway-scout \
  --zone office-doorway \
  --allow-movement \
  --cycles 30 \
  --vision-every 1 \
  --min-step-cm 4 \
  --max-step-cm 36 \
  --stride-chunk-cm 10 \
  --clear-cm 75 \
  --blocked-cm 45 \
  --pause-seconds 0.5 \
  --speak
```

Result summary:

```json
{
  "ok": true,
  "started_movement": true,
  "final_front_distance_cm": 63.8,
  "summary": {
    "counts": {
      "adaptive-move": 7,
      "doorway-creep": 10,
      "scan-turn": 13,
      "recovery-turn": 8,
      "reflex-stop": 30,
      "range-scan": 30,
      "vision": 30,
      "speech": 31
    },
    "max_front_distance_cm": 157.0,
    "min_front_distance_cm": 28.9,
    "best_scan": {"bearing_deg": -40.0, "distance_cm": 158.6},
    "reflex_stop": true
  }
}
```

Post-run sensors:

- battery: `33%`, `7.06V`
- camera ready: true
- display ready: true
- motors armed: true
- ultrasonic ready: true
- front distance after stop: `63.8cm`
- latest repeated reflex record: `front reflex stop: 44.7cm below 45.0cm`

Observed behavior from operator:

> It starts off well, sees the door, starts heading towards it, then randomly says door closed / starts turning when it is probably within 20cm of the doorway.

## Preliminary diagnosis from run data

These are hypotheses to audit against the code.

### 1. Stale `last_reflex_stop` appears to poison the loop

In `rover/service.py`, hallway scout currently appends a `reflex-stop` whenever `body.state.last_reflex_stop` is truthy:

```python
if body.state.last_reflex_stop:
    actions.append({"kind": "reflex-stop", "cycle": cycle, "result": body.state.last_reflex_stop})
    blocked_streak += 1
```

But `last_reflex_stop` is a retained state field in `rover/drivers.py`, not a per-cycle event queue. Once set, later cycles may repeatedly count the same old reflex as new. The latest run shows repeated identical reflex reasons across many cycles:

- early cycles repeat `23.1cm below 45.0cm`
- later cycles repeat `44.7cm below 45.0cm`
- total reported `reflex-stop`: 30 out of 30 cycles

Likely effect:

- `blocked_streak` increases even when there is no fresh reflex stop
- `recovery-turn` fires too often
- Pip turns randomly after the first true reflex stop

Audit target: confirm whether this is actually happening and propose a robust event/freshness model.

Potential fixes to consider:

- track the last handled `last_reflex_stop["time"]` in hallway scout
- clear or consume `last_reflex_stop` after handling, if safe for diagnostics
- store reflex stops as events and only react to new events
- include `fresh_reflex_stop: true/false` in compact output

### 2. Raw front reading can override a fresh centered range scan

Several cycles show contradictions:

- cycle 17: raw `front_distance_cm=43.7` but scan center `86.1`; decision was `scan-turn` because raw front was below blocked threshold
- cycle 18: raw `front_distance_cm=null` but scan center `88.3`; decision was `scan-turn` because raw front was unknown

Because the ultrasonic sensor is turret-mounted, `body.sensors()` can reflect whatever the turret last saw, stale direction, shell clipping, transient bad reads, or a non-centered reading. When a fresh scan exists and includes a center sample, navigation decisions should probably prefer the scan-center reading over the pre-scan raw front value.

Audit target: identify the correct source of truth for forward clearance during hallway scout.

Potential fixes to consider:

- after `reactive_escape_scan`, use `scan_summary.center.distance_cm` as `decision_front_cm`
- use raw `front_value` only as fallback or hard emergency signal
- add conflict resolution when raw front is blocked but scan-center is clear: recenter turret, take median of 3-5 readings, then decide
- log both `raw_front_cm` and `decision_front_cm`

### 3. Doorway traversal needs state/hysteresis, not one-cycle reactive decisions

Doorways naturally produce alternating readings from open hallway, doorframe, angled door panel, wall, and floor. Current hallway scout is mostly stateless per cycle with `blocked_streak` as a simple recovery trigger.

Potential doorway state machine:

1. `approach_doorway`: large-ish adaptive strides while center is clearly open
2. `threshold_creep`: small creeps when center is between blocked and clear thresholds
3. `align_gap`: small scan/turn only when side opening is repeatedly and substantially better
4. `exit_doorway`: once center/front opens above a threshold for N cycles, continue into hallway phase
5. `recover_or_rescue`: only after fresh repeated blocked readings or unsafe vision/hazard

Add hysteresis:

- hard stop/emergency: e.g. `<30-35cm`
- blocked/no-forward: e.g. `<42-45cm`
- doorway creep band: e.g. `45-75cm`
- clear/adaptive: `>75cm`
- require two fresh blocked readings before recovery turn, unless hard emergency

Audit target: propose a simpler but robust version that fits the current codebase.

### 4. Vision/Hermes is not yet truly in the decision loop

The run had `vision: 30`, but `pip-brain` after the run showed:

```json
"latest_vision": null
```

It also showed stale semantic hazards, including an old cat observation around 6040 seconds old. This suggests hallway scout captures/observes, but fresh semantic vision is not becoming an actionable decision input.

Audit targets:

- inspect `vision_awareness_task`, `/vision/analysis`, `pip_brain_snapshot`, and `rover/mapping.py`
- determine why `latest_vision` is null after a vision-heavy hallway run
- propose a compact live vision packet for doorway navigation
- ensure semantic vision cannot override hard ultrasonic safety

Potential architecture:

- Pi-local loop owns safety and primitives
- Hermes/Cleo brain receives compact packets every few cycles or at uncertainty points
- Hermes returns high-level intent only, not motor PWM/instant brake commands
- Pi validates all intents before movement

Example high-level brain response schema:

```json
{
  "intent": "continue_doorway_creep",
  "confidence": 0.72,
  "reason": "scan center is clear and image shows open doorway",
  "max_step_cm": 4,
  "preferred_bearing_deg": 0,
  "speak": "I think the doorway is still open. I am creeping through slowly.",
  "stop_if": ["front_below_40cm", "cat_seen", "image_path_blocked"]
}
```

## Files likely relevant

Start here:

- `rover/service.py`
  - `move_step`
  - `adaptive_forward_step_cm`
  - `adaptive_forward_stride`
  - `rotate_step`
  - `reactive_escape_scan`
  - `hallway_scout_scan_turn`
  - `_hallway_scout_task`
  - `vision_awareness_task`
  - `pip_brain_snapshot`
- `rover/drivers.py`
  - `SimState.last_reflex_stop`
  - `_check_forward_reflex`
  - `drive`
  - `sensors`
- `rover/models.py`
  - `HallwayScoutCommand`
  - `VisionAwarenessCommand`
  - possible new command/schema for brain-assisted doorway scout
- `rover/client.py`
  - `hallway-scout` CLI
  - possible CLI flags for brain assistance or doorway mode
- `rover/pip_brain.py`
  - why latest vision is null
  - how spatial memory, hazards, and recent events are summarized
- `rover/hermes_bridge.py`
  - existing Hermes API bridge pattern
- `rover/mapping.py`
  - semantic event extraction and spatial memory
- `tests/`
  - add regression coverage before motion behavior changes
- `docs/HANDOVER_2026-06-25_PIP_HALLWAY.md`
  - previous hallway scout handover

## Questions for the audit

Please answer these before changing code:

1. Is stale `last_reflex_stop` definitely causing repeated false blocked streaks?
2. Should hallway scout prefer scan-center over raw front after a fresh scan?
3. What is the safest minimal doorway state machine that improves behavior without overcomplicating the Pi loop?
4. Why does `pip-brain` show `latest_vision: null` after many `vision` actions?
5. What compact brain packet should Pip send to Hermes/Cleo for high-level decisions?
6. What should Hermes be allowed to return, and how should the Pi validate/refuse it?
7. Which changes can be tested in sim/unit tests before any real floor run?
8. What telemetry should compact hallway-scout output include so future debugging is obvious?

## Suggested implementation plan after audit

A good patch sequence might be:

1. Add tests for stale reflex freshness and hallway-scout decision logic.
2. Fix stale reflex handling without changing movement tuning.
3. Add `raw_front_cm`, `scan_center_cm`, and `decision_front_cm` telemetry.
4. Use scan-center as primary clearance after scan, with median recenter/resample on conflicts.
5. Add doorway hysteresis/state for `office-doorway` style runs.
6. Fix fresh vision ingestion so `pip-brain` has current `latest_vision`.
7. Add optional brain-assisted high-level intent mode, keeping Pi-local safety authoritative.
8. Only then run a short supervised hardware test.

## Expected verification before hardware

Run from repo root:

```bash
python -m pytest -q
CLEO_ROVER_MODE=sim uvicorn rover.service:app --host 127.0.0.1 --port 8099
python scripts/smoke_test.py
```

If adding new behavior, include targeted tests for:

- stale reflex stops are not double-counted
- scan-center clear/raw-front blocked conflict resolves safely
- doorway creep does not turn endlessly when center remains in the creep band
- hard blocked readings still stop/turn/refuse movement
- brain/Hermes intent cannot bypass local safety

## Current operator preference

The operator wants Pip to feel smarter and more connected to Cleo/Hermes, but not reckless. The desired direction is:

- better navigation around doorways
- better image/brain connectivity
- concise but meaningful speech
- local safety still authoritative
- richer summaries that explain why Pip moved, crept, turned, or asked for help
