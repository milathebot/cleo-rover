"""Tests for the behavior-arbitration brain stem + quiet hours."""

from __future__ import annotations

from fastapi.testclient import TestClient

from rover.arbiter import (
    BEHAVIOR_HOLD,
    BEHAVIOR_OBSERVE,
    BEHAVIOR_PATROL,
    BEHAVIOR_PURSUE_GOAL,
    BEHAVIOR_REST,
    BEHAVIOR_RETURN_TO_CHARGER,
    BEHAVIOR_SOCIALIZE,
    arbitrate,
    in_quiet_hours,
)
from rover.service import app

client = TestClient(app)


def test_arbitrate_priority_order():
    assert arbitrate({"mode": "sleep"})["behavior"] == BEHAVIOR_REST
    assert arbitrate({"battery_recommendation": "charge_before_movement"})["behavior"] == BEHAVIOR_RETURN_TO_CHARGER
    assert arbitrate({"battery_percent": 30, "return_to_charger_min_battery": 35, "movement_allowed": True, "dock_known": True})["behavior"] == BEHAVIOR_RETURN_TO_CHARGER
    assert arbitrate({"hazards_present": True})["behavior"] == BEHAVIOR_HOLD
    assert arbitrate({"quiet": True, "movement_allowed": True, "curiosity": 0.9})["behavior"] == BEHAVIOR_OBSERVE
    assert arbitrate({"person_present": True})["behavior"] == BEHAVIOR_SOCIALIZE
    assert arbitrate({"has_goal": True})["behavior"] == BEHAVIOR_PURSUE_GOAL
    assert arbitrate({"movement_allowed": True, "curiosity": 0.9})["behavior"] == BEHAVIOR_PATROL
    assert arbitrate({"movement_allowed": True, "curiosity": 0.1, "boredom": 0.1})["behavior"] == BEHAVIOR_OBSERVE


def test_quiet_hours_wraps_midnight():
    q = {"enabled": True, "start": "23:30", "end": "09:00"}
    assert in_quiet_hours(23 * 60 + 45, q) is True
    assert in_quiet_hours(2 * 60, q) is True
    assert in_quiet_hours(12 * 60, q) is False
    assert in_quiet_hours(8 * 60, {"enabled": False, "start": "23:30", "end": "09:00"}) is False


def test_arbiter_status_default_off():
    data = client.get("/pip/arbiter").json()
    assert data["enabled"] is False
    assert data["running"] is False
    assert "behavior" in data["would_choose"]


def test_arbiter_tick_runs_in_sim():
    data = client.post("/pip/arbiter/tick").json()
    assert data["ok"] is True
    assert "behavior" in data["decision"]
    assert "result" in data
