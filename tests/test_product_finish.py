"""Tests for the product-finish surfaces: degradation, task history, live control."""

from __future__ import annotations

from fastapi.testclient import TestClient

from rover import service

client = TestClient(service.app)


def test_health_degradation_endpoint():
    d = client.get("/health/degradation").json()
    assert d["ok"] is True
    assert d["level"] in ("full", "scan_only", "turret_only", "stopped")
    assert "reasons" in d and d["reasons"]
    # In sim (bench-safe / disarmed) Pip cannot drive but can still scan/look.
    assert d["allow_drive"] is False


def test_composite_includes_degradation():
    h = client.get("/health/composite").json()
    assert "degradation" in h
    assert h["degradation"]["level"] in ("full", "scan_only", "turret_only", "stopped")


def test_task_history_records_arbiter_ticks():
    client.post("/pip/arbiter/tick?allow_movement=false")
    hist = client.get("/tasks/history").json()
    assert hist["ok"] is True
    assert isinstance(hist["history"], list)
    assert any(str(e.get("task", "")).startswith("arbiter:") for e in hist["history"])
    # Each entry has the unified shape.
    e = hist["history"][0]
    for key in ("task", "at", "duration_s", "did_move", "ok"):
        assert key in e


def test_pip_live_reports_loop_state_in_sim():
    data = client.post("/pip/live?on=true").json()
    assert data["ok"] is True
    assert data["live"] is True
    assert "loops" in data
    # Sim has no hardware, so the loops stay inert -- reported honestly.
    assert data["mode"] == "sim"
    assert data["loops"]["arbiter"] is False


def test_pip_live_pause_is_safe():
    data = client.post("/pip/live?on=false").json()
    assert data["ok"] is True
    assert data["live"] is False
