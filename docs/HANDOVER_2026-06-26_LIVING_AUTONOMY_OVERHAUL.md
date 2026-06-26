# Handover — 2026-06-26 — Living-autonomy overhaul (why Pip didn't roam, and the fix)

Follow-up to the hardware bring-up earlier the same day. The owner reported the first
real run was "good but not great": Pip avoided obstacles but did **none** of the
self-directed behaviours we built — no roaming, no acting on curiosity, no wall-hugging.
This session is a full audit of *why* and a fix so the autonomy actually lives. No
hardware was attached (Pi was powered down); all work is code/config/tests + a wake-up
script for next power-on.

## Root cause (two compounding reasons, both confirmed in code)
1. **The self-directed loop never ran.** `_start_arbiter_loop()` bails unless
   `life_loop.arbiter_enabled` is true, and we (correctly) left it **false** at shutdown
   (boot-safe). So the whole arbiter — patrol, socialize, curiosity, mood-driven
   behaviour — was dormant. What ran was only operator-triggered reactive obstacle
   avoidance when you hit roam/drive.
2. **Even with the arbiter on, autonomous patrol was effectively unreachable.** The
   arbiter fires PATROL on `curiosity >= ~0.68` or `boredom >= 0.6`. But curiosity only
   ever *decayed* toward zero on idle ticks (it only rose on external stimulus), and
   boredom lived in a separate scalar that nothing grew on its own. So an undisturbed
   Pip's drive fell to zero and stayed there — it could never want to explore.

Secondary findings: wall-following was off by default and not on the autonomous path;
frontier/VFH/occupancy mapping were all off, so roaming was aimless widest-gap rather
than directed. (Wall-follow geometry is fine — the turret pans 70° from forward, ~6%
off perpendicular, inside the deadband; an audit claim that it was "3× broken" was
wrong.) The **safety/reflex layer audited clean and authoritative** — 0.0/None/negative
sonar handled fail-closed, `range_hold_ms=700` ≈ 8 cm blind at crawl (covered by median
re-read + watchdog), no bypass path. Left untouched.

## What changed (all on master, all behind the arbiter master-switch)
The "inner life" is now genuine and ebbs/flows. These are **code** fixes — they reach
the Pi via `git pull` + a body restart, no config edit:
- `autonomy.py`: an idle tick relaxes curiosity **toward its personality baseline (0.55)**
  instead of to zero — Pip stays gently curious. An idle tick no longer counts as a
  "stimulus" (so the quiet-time clock is meaningful).
- `service.py life_heartbeat_step()` (always-on, every 20 s): **boredom grows** once it's
  been quiet for `boredom_quiet_seconds` (90 s) by `boredom_growth_per_tick` (0.03), and
  the **mood is coloured** `curious`/`seeking` from the drive — visible on the RGB strip
  and causal (the arbiter lowers the patrol bar when seeking).
- `arbiter.py` + `arbiter_context()`: a **patrol cadence guard** (`patrol_min_gap_seconds`,
  120 s) downgrades PATROL→OBSERVE right after a loop, so Pip explores, settles, then
  explores again instead of thrashing.
- `arbiter_tick()` PATROL: resets boredom (→0.1) and pulls curiosity just under baseline
  after a loop (the ebb), and **weaves a wall-following leg in every 3rd patrol** when
  `nav.wall_follow_enabled` — this is the "hugging walls" behaviour.
- `config.py` LifeLoopConfig: new tunables `boredom_quiet_seconds`, `boredom_growth_per_tick`,
  `patrol_min_gap_seconds`.
- Small: `/voice/event` "heard" now logs a speech event (wake-loop transcripts feed
  autonomy/memory, not just the dashboard). Startup logs a one-line **autonomy posture**
  so "why didn't it roam?" is never a mystery again.

These are **config** changes (per-robot; need the script below to reach the Pi):
- `config/rover.hardware.floor.cautious.json` nav flags flipped **on**: `use_vfh_steering`,
  `mapping_enabled`, `wall_follow_enabled` → directed, frontier-seeking roaming + wall-hug.
  (`config.py` defaults stay OFF so sim/tests keep the conservative widest-gap path —
  414 tests green, +6 new in `tests/test_living_autonomy.py`.)

## Next power-on (step by step)
1. Power on, SSH in, `cd ~/cleo-rover && git pull`.
2. `sudo systemctl restart cleo-rover-body.service` — loads the new code. Check the
   posture line: `journalctl -u cleo-rover-body.service -n 40 | grep 'autonomy posture'`.
3. Enable directed roaming on the live local config (safe, still no self-drive):
   `bash scripts/enable_living_mode.sh` → `sudo systemctl restart cleo-rover-body.service`.
4. **While you're present and watching, baby gate closed**, flip the master switch:
   `bash scripts/enable_living_mode.sh arbiter` → restart. Pip will now roam, act on
   curiosity, and hug walls on its own. `curl -s localhost:8099/pip/arbiter | python3 -m json.tool`
   shows what it'll do next and the live curiosity/boredom/mood.
5. To put it back to boot-safe: `bash scripts/enable_living_mode.sh off` → restart (or just
   reboot — `arbiter_enabled` is not persisted to default-on).

Expect a believable cadence: when undisturbed it gets bored over ~2–3 min and runs a
~30 s roam (frontier-directed; every 3rd is a wall-trace), then settles to observe for
≥120 s, repeat. A person/sound/motion spikes curiosity and brings the next roam sooner.
Low battery / quiet hours (23:30–09:00) / a cliff reflex all still pre-empt it.

## Still open / next
- **Wake word** ("Hey Pip") still blocked on Python 3.13 (no tflite-runtime wheel) — needs
  a py3.11 venv or Porcupine. STT via `/hearing/listen` works.
- Autonomous **room-to-room** is still gated by `approved_zones = ["office"]` and open-loop
  odometry drift — Pip roams within a room well; crossing rooms reliably wants encoders +
  IMU (+ LiDAR). Widen `approved_zones` deliberately if you want it to leave the office.
- Straight-line left veer (needs a per-side duty trim); HC-SR04 motor-noise hardening.
