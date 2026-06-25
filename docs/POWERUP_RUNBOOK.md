# Power-up runbook — from cold boot to autonomous & alive

The exact, ordered sequence to bring Pip up after the overhaul. It is a **joint**
runbook: some steps are physical/config that only the owner can do, some are API
calls the mind (Hermes) makes.

- `[Noot]` = physical / human / config edit (lift wheels, multimeter, edit a profile, hand on stop).
- `[Hermes]` = an API call against the body service (default `http://<pi>:8099`).
- **GATE** = must pass before continuing. Do not skip.
- Config-flag changes mean *edit the floor-cautious profile JSON → restart the
  service* (config loads at startup). Profile switches: `sudo scripts/set_rover_profile.sh <presence|floor-cautious>`.

Reference detail: [`../handover.md`](../handover.md) (operating manual) and
[`HANDOVER_2026-06-25_PIP_FNK0043_AUDIT_AND_BRINGUP.md`](HANDOVER_2026-06-25_PIP_FNK0043_AUDIT_AND_BRINGUP.md)
(calibration). `GET /calibration` returns the same checklist + a
`ready_for_supervised_drive` gate.

> Onboarding read is **one-time**: read `handover.md` once before you first operate
> motion (re-skim after a pull that changes it). You do **not** re-read it per
> command — the per-action safety is enforced at runtime by the Pi (grant + armed
> motors + the calibration gate + the reflex).

---

## Phase 0 — Code current (no robot needed)
1. `[Noot]` On the Pi: `git pull && . .venv/bin/activate && pip install -e '.[pi]'`,
   then `python -m pytest -q` → **365 passed**.
   **GATE:** tests green.

## Phase 1 — Boot, no motion
2. `[Noot]` Battery pack in; rover on a stable surface with **wheels lifted**; hand near power. Power on.
3. `[Noot]` Start in the **no-motor presence profile**:
   `CLEO_ROVER_CONFIG=config/rover.hardware.presence.json CLEO_ROVER_MODE=hardware uvicorn rover.service:app --port 8099`
   (or `sudo scripts/set_rover_profile.sh presence`).
4. `[Noot]` Export the mind env (`HERMES_API_BASE` / `HERMES_API_KEY` / `HERMES_MODEL`).
   `[Hermes]` `GET /mind/status` → `configured: true`.
5. `[Hermes]` `GET /health` and `GET /sensors` → service up; `ultrasonic_ready: true`,
   three line-sensor values, plausible `battery_percent`, camera ready.
   **GATE:** service healthy, sensors reading.

## Phase 2 — Board truth (still no motion)
6. `[Noot]` `i2cdetect -y 1` → `0x40` (PCA9685) + `0x48` (ADS7830) present.
7. `[Noot]` Set **`sensors.pcb_version`** (1 or 2): multimeter the pack vs `[Hermes]`
   `GET /battery` voltage — if the API reads ~33% high, it's **v1** → set `pcb_version: 1`, restart.
   **GATE:** `GET /battery` voltage matches the meter within ~0.1 V.

## Phase 3 — Motion calibration (motors armed, **wheels still lifted**, supervised)
8. `[Noot]` Switch to the motor profile: `sudo scripts/set_rover_profile.sh floor-cautious`.
   Keep wheels **off the floor**.
9. `[Hermes]` grant motion (`POST /movement/grant {"task":"calib","allow_movement":true,"duration_seconds":120,"max_linear":0.25,"max_turn":0.5}`),
   command pan +30° (`POST /turret {"pan_deg":30}`) → `[Noot]` confirm the **sonar rotates RIGHT**;
   center it; hand-cycle ±70° → no chassis binding.
10. `[Hermes]` brief forward (`POST /movement/move-step {"forward_cm":6}`) →
    `[Noot]` confirm **all four wheels roll forward**.
11. `[Noot]` IR polarity: pass a hand / table-edge under the sensors, note the
    "no-floor" value → set `safety.line_drop_value`; confirm it differs from an on-line value.
12. `[Noot]` Coast + odometry: short forward pulses, measure coast-after-stop → set
    `nav.cruise_coast_cm`; run a UMBmark square → tune `odometry.cm_s_per_duty` (~33) and
    `odometry.deg_s_per_turn_duty` (~200).
    **GATE:** pan goes right, wheels go forward, `line_drop_value` set, coast measured.

## Phase 4 — Cliff reflex on (wheels lifted, over a real edge)
13. `[Noot]` Set `safety.cliff_reflex_enabled: true` (with the measured `line_drop_value`);
    restart. Hold the rover over a table edge → `[Hermes]` `GET /sensors` shows
    `last_reflex_stop.kind == "cliff"`. Leave `bumper_reflex_enabled` **off** (no switches on this board).
    **GATE:** cliff reflex fires on a real edge.

## Phase 5 — First supervised floor drive
14. `[Noot]` Rover on the floor, area clear, **hand on stop**. `[Hermes]` `GET /calibration`
    → **`ready_for_supervised_drive: true`**; `GET /health/composite` → no blockers besides intent.
15. `[Hermes]` grant a short motion, run `POST /tasks/reactive-explore {"allow_movement":true,"duration_seconds":30}`
    → confirm it drives, stops, and the reflex behaves on the floor.
    **GATE:** clean supervised drive + stop.

## Phase 6 — Teach the map (so it can come home)
16. `[Noot+Hermes]` Move it room-to-room; at each spot `POST /topo/observe?name=<place>`.
    **At the dock: `POST /topo/observe?name=charger`** — this gives return-home its anchors.
    **GATE:** `GET /topo/graph` shows your places, including a charger node.

## Phase 7 — Go alive (the arbiter) — supervised first
17. `[Noot]` Set `life_loop.arbiter_enabled: true`; restart. `[Hermes]` `POST /pip/live?on=true`.
18. `[Hermes]` poll `GET /health/composite`, `GET /pip/arbiter`, and **watch `GET /pip/interrupts`**;
    steer with `POST /pip/goal` / `set_goal`. `[Noot]` supervise, hand on stop. Confirm it returns to
    the charger when battery drops and respects quiet hours.
    **GATE:** a few clean self-directed minutes; return-to-charger works.

## Phase 8 — Smooth continuous motion (last)
19. `[Noot]` Set `nav.continuous_motion_enabled: true`; restart. `[Hermes]` validate with
    `POST /pip/cruise?dry_run=true` on the floor, then `?on=true` — supervised.
    Optional after this: voice (`cleo-rover-voice`); vision (`pip install '.[vision]'` + `nav.flow_stall_enabled: true`).

**At that point Pip is alive:** arbiter + heartbeat + RGB running, mapping +
consolidating as it roams, returning home to charge, expressing via RGB, narrating
via `/life/diary`. Hermes supplies goals + persona, polls `/health/composite`, and
answers `/pip/interrupts`.

---

## Routine power-up (after calibration is done once)

The calibration values (`pcb_version`, `line_drop_value`, `cruise_coast_cm`,
odometry) persist in the config, so Phases 2–4 are **one-time** unless hardware
changes. Every subsequent power-up is short:

1. `[Noot]` Power on (floor-cautious profile), clear area, hand on stop.
2. `[Hermes]` `GET /calibration` → `ready_for_supervised_drive: true`; `GET /health/composite` clean.
3. `[Hermes]` `POST /pip/live?on=true` → it wakes up and runs; steer with goals, watch interrupts.

---

## The contract that holds through all of this

A move only ever happens with an **active grant + armed motors + a clear reflex**,
and never before `GET /calibration.ready_for_supervised_drive == true`. Every drive
pulse is independently re-checked by the reflex / bearing-guard / watchdog. A
refused command (e.g. the bench-safe `/drive` rejection) is the contract working —
not an error to route around. The mind is advisory and can only ever make Pip do
*less*; the Pi-local safety floor is authoritative.
