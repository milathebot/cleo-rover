"""Tests for exploration helpers + return-to-landmark."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from rover import explore
from rover.models import SpatialMemoryItem
from rover.service import app

client = TestClient(app)


def test_decay_confidence_weakens_with_age():
    assert explore.decay_confidence(0.8, 0) == 0.8
    decayed = explore.decay_confidence(0.8, 1800, half_life_s=1800)
    assert 0.35 < decayed < 0.45  # ~one half-life
    assert explore.decay_confidence(0.8, 100000) < 0.05


def test_memory_bias_splits_avoid_and_prefer():
    now = time.time()
    near = SpatialMemoryItem(id="n", label="wall", kind="range_scan", bearing_deg=-40.0, distance_m=0.3, confidence=0.8, last_seen_at=now)
    far = SpatialMemoryItem(id="f", label="opening", kind="range_scan", bearing_deg=30.0, distance_m=1.8, confidence=0.8, last_seen_at=now)
    bias = explore.memory_bias([near, far], now=now)
    assert -40.0 in bias["avoid_bearings"]
    assert 30.0 in bias["prefer_bearings"]


def test_memory_bias_ignores_stale_low_confidence():
    now = time.time()
    stale = SpatialMemoryItem(id="s", label="wall", kind="range_scan", bearing_deg=-40.0, distance_m=0.3, confidence=0.5, last_seen_at=now - 20000)
    bias = explore.memory_bias([stale], now=now)
    assert bias["avoid_bearings"] == []  # decayed below the confidence floor


def test_prioritize_scan_angles_orders_preferred_first():
    bias = {"prefer_bearings": [40.0], "avoid_bearings": [-40.0]}
    ordered = explore.prioritize_scan_angles([-40, -20, 0, 20, 40], bias)
    assert ordered[0] == 40  # preferred bearing looked at first
    assert ordered[-1] == -40  # avoided bearing last


def test_nearest_landmark_and_bearing_to_turn():
    a = SpatialMemoryItem(id="a", label="charging dock", kind="dock", bearing_deg=30.0, distance_m=2.0, confidence=0.7)
    b = SpatialMemoryItem(id="b", label="charging dock", kind="dock", bearing_deg=-10.0, distance_m=0.8, confidence=0.7)
    nearest = explore.nearest_landmark([a, b], label="charging")
    assert nearest.id == "b"
    assert -25.0 <= explore.bearing_to_turn(nearest.bearing_deg) <= 25.0


def test_return_to_unknown_landmark_is_graceful():
    data = client.post("/tasks/return-to?label=nonexistent-thing-xyz").json()
    assert data["ok"] is True
    assert data["found"] is False


def test_return_to_finds_remembered_landmark():
    client.post(
        "/map/remember",
        json={"id": "charger-dock", "label": "Charging dock", "kind": "dock", "zone": "office", "bearing_deg": 35.0, "distance_m": 1.5, "confidence": 0.8},
    )
    data = client.post("/tasks/return-to?label=charging").json()
    assert data["found"] is True
    assert data["target"]["kind"] == "dock"
    assert data["turn_deg"] != 0.0
