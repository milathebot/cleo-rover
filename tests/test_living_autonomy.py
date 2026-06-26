"""The 'living being' autonomy dynamics: the fixes that make Pip actually roam and
act on curiosity on its own (last hardware run it never did, because curiosity only
decayed and boredom never grew, so the arbiter's PATROL was effectively unreachable).

These lock in: curiosity relaxes toward its baseline instead of dying to zero, an
idle tick is not a 'stimulus', boredom grows while it's quiet, and the arbiter's
patrol has a cadence guard so it ebbs and flows instead of thrashing.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from rover.arbiter import BEHAVIOR_OBSERVE, BEHAVIOR_PATROL, arbitrate
from rover.autonomy import AutonomyEngine
from rover.config import LifeLoopConfig
from rover.models import RoverEvent, RoverEventKind
from rover.service import app, autonomy, pip_state

client = TestClient(app)

BASELINE = LifeLoopConfig().personality.curiosity  # 0.55


def test_idle_tick_relaxes_curiosity_toward_baseline_not_zero():
    eng = AutonomyEngine(config=LifeLoopConfig())
    # From well above baseline it eases DOWN to the baseline (and stops there).
    eng.state.curiosity = 0.95
    for _ in range(100):
        eng.update_from_event(RoverEvent(kind=RoverEventKind.idle_tick, source="t"))
    assert abs(eng.state.curiosity - BASELINE) < 0.02
    # From below baseline it drifts back UP -- an undisturbed Pip stays curious,
    # it doesn't go inert (which is what killed autonomous patrol before).
    eng.state.curiosity = 0.05
    for _ in range(300):
        eng.update_from_event(RoverEvent(kind=RoverEventKind.idle_tick, source="t"))
    assert eng.state.curiosity >= BASELINE - 0.02


def test_idle_tick_is_not_counted_as_a_stimulus():
    eng = AutonomyEngine(config=LifeLoopConfig())
    eng.update_from_event(RoverEvent(kind=RoverEventKind.speech, source="t", timestamp=1000.0))
    assert eng.state.last_stimulus_at == 1000.0
    # An idle tick must NOT reset the 'how long has it been quiet?' clock, or boredom
    # could never grow during quiet time.
    eng.update_from_event(RoverEvent(kind=RoverEventKind.idle_tick, source="t", timestamp=5000.0))
    assert eng.state.last_stimulus_at == 1000.0
    # A real stimulus does reset it.
    eng.update_from_event(RoverEvent(kind=RoverEventKind.motion, source="t", timestamp=6000.0))
    assert eng.state.last_stimulus_at == 6000.0


def test_boredom_alone_triggers_patrol():
    assert arbitrate({"movement_allowed": True, "curiosity": 0.0, "boredom": 0.7})["behavior"] == BEHAVIOR_PATROL


def test_seeking_mood_lowers_the_patrol_bar():
    # 0.6 curiosity is under the neutral 0.68 bar but over the 0.55 'seeking' bar.
    assert arbitrate({"movement_allowed": True, "curiosity": 0.6})["behavior"] == BEHAVIOR_OBSERVE
    assert arbitrate({"movement_allowed": True, "curiosity": 0.6, "mood": "seeking"})["behavior"] == BEHAVIOR_PATROL


def test_patrol_cadence_guard_downgrades_to_observe():
    # Very curious + free to move would normally patrol...
    assert arbitrate({"movement_allowed": True, "curiosity": 0.95})["behavior"] == BEHAVIOR_PATROL
    # ...but right after a loop it observes instead of thrashing.
    assert arbitrate({"movement_allowed": True, "curiosity": 0.95, "patrol_cooldown_active": True})["behavior"] == BEHAVIOR_OBSERVE


def test_heartbeat_grows_boredom_while_quiet():
    saved = {k: pip_state.get(k) for k in ("boredom", "mode", "mood")}
    saved_stim = autonomy.state.last_stimulus_at
    try:
        pip_state["mode"] = "social"
        pip_state["boredom"] = 0.0
        before = pip_state["boredom"]
        for _ in range(5):
            autonomy.state.last_stimulus_at = time.time() - 1000.0  # keep it 'quiet'
            client.post("/autonomy/heartbeat")
        assert pip_state["boredom"] > before
    finally:
        for k, v in saved.items():
            pip_state[k] = v
        autonomy.state.last_stimulus_at = saved_stim
