"""Tests for the goal/mission layer (operator + LLM-mind set, local execute)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from rover import mind
from rover.service import app

client = TestClient(app)


def teardown_function(_func):
    # Goals persist in pip_state; clear so they don't leak into other tests.
    client.delete("/pip/goal")


def test_goal_set_get_clear():
    s = client.post("/pip/goal", json={"kind": "explore_zone", "target": "kitchen"}).json()
    assert s["goal"]["kind"] == "explore_zone"
    g = client.get("/pip/goal").json()
    assert g["goal"]["target"] == "kitchen"
    client.delete("/pip/goal")
    assert client.get("/pip/goal").json()["goal"] is None


def test_mind_can_set_a_goal(monkeypatch):
    monkeypatch.setattr(mind, "mind_configured", lambda: True)
    monkeypatch.setattr(
        mind,
        "ask_mind_for_intent",
        lambda **_: {"ok": True, "intent": {"intent": "set_goal", "params": {"goal_kind": "explore_zone", "target": "hallway"}}},
    )
    data = client.post("/mind/step").json()
    assert data["source"] == "mind"
    assert data["set_goal"]["kind"] == "explore_zone"
    assert data["set_goal"]["target"] == "hallway"


def test_invalid_goal_kind_rejected():
    r = client.post("/pip/goal", json={"kind": "launch_rockets", "target": "moon"})
    assert r.status_code == 422  # pydantic pattern rejects unknown kinds
