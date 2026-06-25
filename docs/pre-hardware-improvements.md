> ⚠️ **HISTORICAL session handoff** (pre-overhaul). Superseded by the current
> system — see [`../handover.md`](../handover.md) + [`../README.md`](../README.md).

# Cleo Rover Mk1 pre-hardware hardening

Implemented before parts arrive:

1. Persistent SQLite autonomy state, events, cooldowns, and spatial memory.
2. Personality/life-loop config in `config/rover.default.json`.
3. Cleo Hub bridge via `/cleo-hub` and autonomy quiet-mode awareness.
4. Autonomy dashboard at `/autonomy/dashboard`.
5. Expanded non-human expression modes: curious, watching, seeking, sleeping, shy, proud, low_power.
6. Safety simulator at `/safety/simulate`.
7. Calibration wizard: `cleo-rover-calibrate`.
8. Senses daemon stub: `cleo-rover-senses`.
9. Systemd unit templates in `deploy/systemd/`.
10. Explicit restraint reasons in behavior decisions.
11. Spatial memory/map scaffold via `/map` and `/map/remember`.

## Spatial memory / mapping

Mk1 cannot do true SLAM before hardware. What it can do now is store landmark/object memories:

- label: `desk`, `charger`, `door`, `cat tree`
- kind: `place`, `object`, `dock`, `hazard`
- zone: `office`, `desk area`, `hallway`
- bearing/distance estimates when available
- confidence and observation count

Once camera/motion data exists, vision can upsert landmarks. Once wheel odometry/IMU exists, this can evolve into a simple topological map: named zones and transitions, not centimeter-perfect navigation.
