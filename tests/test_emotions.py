"""Tests for the unified emotion engine + internal heartbeat (the 'soul')."""

from __future__ import annotations

from fastapi.testclient import TestClient

from rover import service
from rover.service import app

client = TestClient(app)


def test_autonomy_heartbeat_refreshes_energy_from_battery(monkeypatch):
    monkeypatch.setattr(service.body, "sensors", lambda: {"battery_percent": 90.0, "errors": {}})
    data = client.post("/autonomy/heartbeat").json()
    assert data["ok"] is True
    assert "feelings" in data
    assert data["feelings"]["energy"] >= 0.85


def test_low_battery_drops_energy(monkeypatch):
    monkeypatch.setattr(service.body, "sensors", lambda: {"battery_percent": 12.0, "errors": {}})
    data = client.post("/autonomy/heartbeat").json()
    assert data["feelings"]["energy"] <= 0.2


def test_pip_state_exposes_unified_feelings():
    data = client.get("/pip/state").json()
    assert "feelings" in data
    for key in ("mood", "energy", "curiosity", "attention", "confidence", "boredom"):
        assert key in data["feelings"]


def test_pip_brain_self_includes_energy_and_confidence():
    brain = client.get("/pip/brain").json()
    assert "energy" in brain["self"]
    assert "confidence" in brain["self"]


def test_heartbeat_not_autostarted_in_sim():
    # The background heartbeat must stay off in sim/test mode (hardware-only),
    # so it cannot inject background events under the test client.
    assert service._heartbeat_task is None
