"""Service-level tests for the Tier 3 nav/topo/memory endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from rover.service import app

client = TestClient(app)


def test_nav_plan_returns_steering_grid_and_frontiers():
    r = client.post("/nav/plan", json={"zone": "test", "angles": [-40, -20, 0, 20, 40], "settle_ms": 50})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "steering" in data and "chosen_bearing_deg" in data["steering"]
    assert "frontiers" in data
    assert data["grid"]["size_cells"] >= 11


def test_nav_grid_and_reset():
    assert client.get("/nav/grid").json()["ok"] is True
    reset = client.post("/nav/grid/reset").json()
    assert reset["reset"] is True
    assert reset["stats"]["updates"] == 0


def test_topo_observe_graph_and_plan():
    # First place.
    a = client.post("/topo/observe", params={"name": "office"}, json={"zone": "office", "angles": [-40, -20, 0, 20, 40], "settle_ms": 50}).json()
    assert a["ok"] is True
    graph = client.get("/topo/graph").json()
    assert graph["ok"] is True
    assert graph["summary"]["places"] >= 1
    # Planning to a known place from the current node succeeds or fails gracefully.
    plan = client.get("/topo/plan", params={"to": "office"}).json()
    assert "ok" in plan


def test_topo_plan_unknown_goal_is_graceful():
    client.post("/topo/observe", params={"name": "spot"}, json={"zone": "spot", "angles": [0], "settle_ms": 50})
    plan = client.get("/topo/plan", params={"to": "nowhere-xyz"}).json()
    assert plan["ok"] is False


def test_memory_consolidate_promotes_repeated_landmark():
    item = {"id": "charger-x", "label": "charger", "kind": "vision_object", "zone": "lab", "confidence": 0.7}
    for _ in range(3):  # upsert increments observations -> reaches promote_n
        client.post("/map/remember", json=item)
    res = client.post("/memory/consolidate").json()
    assert res["ok"] is True
    facts = client.get("/memory/facts").json()["facts"]
    assert any(f["subject"] == "charger" and f["object"] == "lab" for f in facts)


def test_wall_follow_disabled_by_default():
    r = client.post("/tasks/wall-follow", params={"allow_movement": False}).json()
    assert r["ok"] is False
    assert "disabled" in r["reason"]


def test_vision_flow_advisory_unavailable_in_sim():
    r = client.post("/vision/flow").json()
    assert r["ok"] is True
    assert r["available"] is False  # no OpenCV + live camera in sim
