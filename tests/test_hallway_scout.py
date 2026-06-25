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

from fastapi.testclient import TestClient

from rover.service import app

client = TestClient(app)


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
