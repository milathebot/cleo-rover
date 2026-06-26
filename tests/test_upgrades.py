"""Tests for the 'while charging' upgrade batch: long-term memory for the mind,
odometry calibration, frontier-driven roaming + costmap inflation, causal mood,
and the lifespan migration."""

from __future__ import annotations

from fastapi.testclient import TestClient

from rover import arbiter, explore, longterm, odometry
from rover.config import RoverConfig
from rover.occupancy import OccupancyGrid, grid_config_from
from rover.odometry import MotionModel
from rover.service import app

client = TestClient(app)


# --- odometry calibration -----------------------------------------------------


def test_odometry_calibration_inverts_the_model():
    m = MotionModel()
    # forward: a known pulse travels distance_cm_for; solving must recover cm_s_per_duty
    cm = m.distance_cm_for(0.4, 1500)
    solved = odometry.calibrate_cm_s_per_duty(measured_cm=cm, duty=0.4, duration_ms=1500, duty_deadband=m.duty_deadband, dead_time_ms=m.dead_time_ms)
    assert abs(solved - m.cm_s_per_duty) < 0.01
    # turn: same round-trip
    deg = m.degrees_for(0.45, 800)
    solved_t = odometry.calibrate_deg_s_per_turn_duty(measured_deg=deg, turn_duty=0.45, duration_ms=800, turn_deadband=m.turn_deadband, dead_time_ms=m.dead_time_ms)
    assert abs(solved_t - m.deg_s_per_turn_duty) < 0.01


def test_odometry_calibration_detects_under_count():
    # If reality moved 2x what the default model expected, the solved coefficient ~2x.
    m = MotionModel()
    model_cm = m.distance_cm_for(0.4, 1500)
    solved = odometry.calibrate_cm_s_per_duty(measured_cm=model_cm * 2, duty=0.4, duration_ms=1500, duty_deadband=m.duty_deadband, dead_time_ms=m.dead_time_ms)
    assert abs(solved - 2 * m.cm_s_per_duty) < 0.5


def test_calibrate_odometry_endpoint_roundtrip():
    from rover import service

    try:
        status = client.get("/calibrate/odometry").json()
        assert status["ok"] is True and "cm_s_per_duty" in status["live"]
        out = client.post("/calibrate/odometry?linear_cm=20&linear_duty=0.4&linear_ms=1500").json()
        assert out["ok"] is True and "cm_s_per_duty" in out["applied"]
        # applied live + persisted
        assert service.store.load_json("odometry_calibration") is not None
        # nothing to calibrate -> graceful
        assert client.post("/calibrate/odometry").json()["ok"] is False
    finally:
        # don't pollute the shared dev DB (would change MOTION on next import)
        service.store.save_json("odometry_calibration", None)


# --- frontier-driven roaming + inflation --------------------------------------


def test_choose_frontier_bearing_prefers_in_range_nearest():
    assert explore.choose_frontier_bearing([{"bearing_deg": 170}, {"bearing_deg": 30}], max_abs_bearing=120) == 30.0
    assert explore.choose_frontier_bearing([{"bearing_deg": 170}], max_abs_bearing=120) is None
    assert explore.choose_frontier_bearing([], max_abs_bearing=120) is None


def test_costmap_inflation_geometry():
    grid = OccupancyGrid(config=grid_config_from(RoverConfig().nav))
    obstacles = {(5, 5)}
    assert grid.is_near_obstacle(5, 6, 1, obstacles) is True
    assert grid.is_near_obstacle(7, 7, 1, obstacles) is False
    assert grid.is_near_obstacle(7, 7, 2, obstacles) is True


def test_nav_frontier_endpoint():
    data = client.get("/nav/frontier").json()
    assert data["ok"] is True
    assert "frontiers" in data and "chosen_bearing_deg" in data


# --- long-term memory ---------------------------------------------------------


def test_longterm_memory_composes_narrative():
    lm = longterm.compose_longterm_memory(
        facts=[{"subject": "charger", "predicate": "is in", "object": "office", "confidence": 0.9}],
        places=["office", "hallway"],
        spatial_items=[{"label": "cat", "kind": "vision_pet"}, {"label": "Noot", "kind": "vision_person"}],
        journal=[{"day": "d1", "summary": "A calm day."}],
        cat_sightings_recent=2,
    )
    assert "office" in lm["narrative"]
    assert "charger" in " ".join(lm["facts"])
    assert "cat" in lm["people"]
    assert lm["cat_sightings_recent"] == 2


def test_longterm_memory_empty_is_graceful():
    lm = longterm.compose_longterm_memory()
    assert "getting to know" in lm["narrative"]


def test_brain_packet_includes_long_term_memory():
    from rover.service import pip_brain_snapshot

    brain = pip_brain_snapshot(compact=True)
    assert "long_term_memory" in brain
    assert "narrative" in brain["long_term_memory"]


# --- causal mood --------------------------------------------------------------


def test_mood_raises_or_lowers_patrol_threshold():
    # tired: curiosity 0.7 is NOT enough to roam (threshold 0.82) -> observe
    assert arbiter.arbitrate({"movement_allowed": True, "curiosity": 0.7, "mood": "tired"})["behavior"] == arbiter.BEHAVIOR_OBSERVE
    # curious: 0.6 IS enough (threshold 0.55) -> patrol
    assert arbiter.arbitrate({"movement_allowed": True, "curiosity": 0.6, "mood": "curious"})["behavior"] == arbiter.BEHAVIOR_PATROL
    # neutral mood keeps the original 0.68 bar
    assert arbiter.arbitrate({"movement_allowed": True, "curiosity": 0.6})["behavior"] == arbiter.BEHAVIOR_OBSERVE


# --- hygiene: lifespan actually starts the body ------------------------------


def test_lifespan_starts_and_stops_watchdog():
    # Entering the TestClient context triggers the lifespan startup (the modern
    # replacement for @app.on_event): the safety watchdog must come up.
    with TestClient(app) as live:
        subs = live.get("/health/composite").json()["subsystems"]
        assert subs["watchdog_alive"] is True
