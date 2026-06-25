"""Tests for gentle line following + its cliff-safety pre-emption."""

from __future__ import annotations

from fastapi.testclient import TestClient

from rover import service
from rover.line_follow import decide_line_follow, line_error, search_turn
from rover.service import app

client = TestClient(app)


def test_line_error_weights():
    assert line_error({"left": 0, "center": 1, "right": 0}, 1) == (0.0, 1)
    err, count = line_error({"left": 0, "center": 0, "right": 1}, 1)
    assert err > 0 and count == 1
    err, count = line_error({"left": 1, "center": 0, "right": 0}, 1)
    assert err < 0
    assert line_error({"left": 0, "center": 0, "right": 0}, 1) == (None, 0)


def test_decide_line_follow_steers_toward_line():
    centered = decide_line_follow({"left": 0, "center": 1, "right": 0})
    assert centered["lost"] is False and abs(centered["turn"]) < 1e-6
    right = decide_line_follow({"left": 0, "center": 0, "right": 1})
    assert right["turn"] > 0  # steer right toward the line
    left = decide_line_follow({"left": 1, "center": 0, "right": 0})
    assert left["turn"] < 0
    lost = decide_line_follow({"left": 0, "center": 0, "right": 0})
    assert lost["lost"] is True and lost["linear"] == 0.0


def test_search_turn_follows_last_seen_side():
    assert search_turn(0.5) > 0
    assert search_turn(-0.5) < 0


def test_line_follow_task_no_sensors_in_sim():
    data = client.post("/tasks/line-follow", json={"allow_movement": False, "max_cycles": 2}).json()
    assert data["ok"] is True
    assert data["counts"].get("no-line-sensors", 0) >= 1


def test_line_follow_task_follows_injected_line(monkeypatch):
    monkeypatch.setattr(service.body, "sensors", lambda: {"line_sensors": {"left": 0, "center": 0, "right": 1}, "errors": {}})
    data = client.post(
        "/tasks/line-follow",
        json={"allow_movement": False, "max_cycles": 2, "duration_seconds": 5, "compact": False},
    ).json()
    follows = [item for item in data["plan"] if item["kind"] == "follow-sim"]
    assert follows
    assert follows[0]["decision"]["turn"] > 0


def test_line_follow_motion_path_issues_correct_drive(monkeypatch):
    # Drive the allow_movement=True path with guarded_drive stubbed so we can assert
    # the actual motor command: forward + steer toward the line, grant kept active.
    recorded = []

    async def fake_guarded(cmd, require_permission=False):
        recorded.append(cmd)
        return {"ok": True}

    monkeypatch.setattr(service, "guarded_drive", fake_guarded)
    monkeypatch.setattr(service.body, "sensors", lambda: {"line_sensors": {"left": 0, "center": 0, "right": 1}, "errors": {}})
    monkeypatch.setattr(service.body, "consume_reflex_stop", lambda: None)
    data = client.post("/tasks/line-follow", json={"allow_movement": True, "max_cycles": 2, "duration_seconds": 5}).json()
    assert data["ok"] is True
    assert data["task"]["active"] is True  # grant stayed active
    forward_drives = [c for c in recorded if c.linear > 0]
    assert forward_drives, "no forward drive issued on the motion path"
    assert forward_drives[0].turn > 0  # line is to the right -> steer right


def test_cliff_reflex_preempts_line_follow(monkeypatch):
    monkeypatch.setattr(service.body, "sensors", lambda: {"line_sensors": {"left": 0, "center": 1, "right": 0}, "errors": {}})
    monkeypatch.setattr(service.body, "consume_reflex_stop", lambda: {"reason": "cliff/floor-drop reflex", "kind": "cliff", "time": 1.0})
    data = client.post("/tasks/line-follow", json={"allow_movement": True, "max_cycles": 5}).json()
    assert data["counts"].get("reflex-stop", 0) == 1
    assert data["counts"].get("follow", 0) == 0
