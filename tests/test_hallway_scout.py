"""Coverage for the hallway-scout doorway task.

Phase 0 establishes the stable API-boundary invariants that must hold both before
and after the Phase 1 doorway-navigation fixes:

  * observe-only (allow_movement=False) never starts movement and returns an
    observation result, and
  * requesting movement in the default bench/sim profile is refused at preflight
    (motors are not armed), so the task fails closed.

Phase 1 adds unit tests for the pure per-cycle decision logic (`decide_hallway_action`).
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from rover.config import RoverConfig
from rover.drivers import RoverBody
from rover.service import app

client = TestClient(app)


def test_consume_reflex_stop_returns_event_once_then_stays_quiet():
    """Regression for D1: a stale reflex must not re-fire every cycle."""
    body = RoverBody(mode="sim", config=RoverConfig())
    assert body.consume_reflex_stop() is None  # nothing yet

    now = time.time()
    body.state.last_reflex_stop = {"reason": "front reflex", "time": now}
    first = body.consume_reflex_stop()
    assert first is not None and first["time"] == now
    # Same retained reflex is no longer handed back (no phantom blocked streak).
    assert body.consume_reflex_stop() is None
    assert body.consume_reflex_stop() is None

    # A genuinely newer reflex event is delivered once.
    newer = now + 1.0
    body.state.last_reflex_stop = {"reason": "front reflex", "time": newer}
    again = body.consume_reflex_stop()
    assert again is not None and again["time"] == newer
    assert body.consume_reflex_stop() is None


def test_reflex_threshold_is_configurable_and_no_longer_pinned_at_45():
    # Default profile: reflex floor is the configured 30 (was hardcoded max(45,...)).
    body = RoverBody(mode="sim", config=RoverConfig())
    assert body._reflex_threshold_cm() == 30.0
    # front_stop still acts as a lower bound if it is higher than reflex_hard_cm.
    cfg = RoverConfig.model_validate({"safety": {"reflex_hard_cm": 20, "front_stop_distance_cm": 35}})
    assert RoverBody(mode="sim", config=cfg)._reflex_threshold_cm() == 35.0


def test_hallway_scout_observe_only_never_moves():
    r = client.post(
        "/tasks/hallway-scout",
        json={"zone": "office-doorway", "allow_movement": False, "cycles": 2, "vision_every": 0},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["started_movement"] is False
    # Observe-only path returns a preflight + observe-only action, no movement grant.
    kinds = {action.get("kind") for action in data["actions"]}
    assert "observe-only" in kinds


def test_hallway_scout_with_movement_is_refused_in_bench_profile():
    r = client.post(
        "/tasks/hallway-scout",
        json={"zone": "office-doorway", "allow_movement": True, "cycles": 2, "vision_every": 0, "speak": False},
    )
    assert r.status_code == 200
    data = r.json()
    # Bench/sim profile is not floor-cautious + motors unarmed, so preflight blocks it.
    assert data["started_movement"] is False
    assert data["ok"] is False
    assert "preflight" in data["reason"]
