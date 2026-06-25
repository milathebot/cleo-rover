"""Tests for on-Pi vision + the perception->brain ingestion fix."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from rover import vision_service
from rover.models import SpatialMemoryItem
from rover.pip_brain import _hazards
from rover.service import app

client = TestClient(app)


def test_analyze_frame_degrades_to_placeholder_without_image():
    out = vision_service.analyze_frame(None, zone="office")
    assert out["source"] == "vision_local_placeholder"
    assert out["labels"] == ["scene"]
    assert out["confidence"] < 0.5
    assert out["clear_path"] is None


def test_analyze_frame_missing_file_is_placeholder():
    out = vision_service.analyze_frame("does/not/exist.jpg", zone="hallway")
    assert out["source"] == "vision_local_placeholder"
    assert out["zone"] == "hallway"


def test_vision_backends_reports_known_keys():
    backends = vision_service.vision_backends()
    for key in ("tflite_runtime", "picamera2", "opencv", "numpy", "pillow"):
        assert key in backends
        assert isinstance(backends[key], bool)


def test_hazards_from_labels():
    assert vision_service._hazards_from_labels(["cat", "wall", "person"]) == ["cat", "person"]
    assert vision_service._hazards_from_labels(["wall"]) == []


def test_pip_brain_latest_vision_survives_event_flood():
    # The D7 fix: a real vision analysis must reach the brain even when hundreds
    # of per-angle scan/observation events flood the recent window.
    posted = client.post(
        "/vision/analysis",
        json={"summary": "a cat on the rug", "labels": ["cat"], "confidence": 0.82, "zone": "office", "clear_path": False, "hazards": ["cat"]},
    )
    assert posted.status_code == 200
    for i in range(60):
        client.post("/events", json={"kind": "map_observation", "source": "flood", "label": f"scan {i}"})
    brain = client.get("/pip/brain").json()
    latest = brain["what_is_around_me"]["latest_vision"]
    assert latest is not None
    assert "cat" in (latest.get("labels") or [])


def test_hazards_age_gate_suppresses_stale_sightings():
    now = time.time()
    fresh = SpatialMemoryItem(id="cat-fresh", label="cat", kind="vision_pet", last_seen_at=now)
    stale = SpatialMemoryItem(id="cat-stale", label="cat", kind="vision_pet", last_seen_at=now - 6040)
    sensors = {"front_distance_cm": None}
    fresh_h = _hazards([], [fresh], sensors, stop_cm=18.0, max_item_age_s=120.0)
    stale_h = _hazards([], [stale], sensors, stop_cm=18.0, max_item_age_s=120.0)
    assert any(h["kind"] == "vision_pet" for h in fresh_h)
    assert not any(h["kind"] == "vision_pet" for h in stale_h)
