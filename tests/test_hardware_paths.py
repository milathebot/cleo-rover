"""Hardware-path integration tests via a fake ARMED body.

The adversarial review noted that motor-armed paths (return-home traversal, the
drive/grant glue) are structurally unreachable by the normal sim tests (sim has
no hardware, so motors are never armed). This harness builds a RoverBody in
hardware mode with a dummy motor driver + faked sensors, so the real async
flows actually run -- catching integration crashes and verifying motion happens
end to end while the safety floor stays intact.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from rover import service
from rover.config import RoverConfig


class DummyHW:
    def __init__(self, config):
        self.drives = 0
        self.turret_calls = 0
        self.last = None

    def drive(self, command):
        self.drives += 1
        self.last = command

    def stop(self):
        pass

    def set_turret(self, command):
        self.turret_calls += 1

    def close(self):
        pass


def _armed_body(monkeypatch, front_cm=200.0):
    import rover.drivers as drivers

    monkeypatch.setattr(drivers, "FreenoveHardware", DummyHW)
    # drive_safety/guarded_drive read the MODULE CONFIG (not the body's), so the
    # armed path is only reachable when the module profile is also motor-armed.
    monkeypatch.setattr(service.CONFIG.safety, "bench_safe_no_motors", False)
    cfg = RoverConfig.model_validate({"safety": {"bench_safe_no_motors": False, "front_stop_distance_cm": 18, "reflex_hard_cm": 30}})
    b = drivers.RoverBody(mode="hardware", config=cfg)
    assert b.motors_armed is True
    snap = {"front_distance_cm": front_cm, "line_sensors": None, "bumpers": None, "battery_voltage": None, "battery_percent": None, "ultrasonic_ready": True, "errors": {}}
    monkeypatch.setattr(b, "_sensor_snapshot", lambda: snap)
    monkeypatch.setattr(b, "sensors", lambda: dict(snap))  # the public method reads real GPIO otherwise
    monkeypatch.setattr(b, "front_distance_median", lambda samples=5: front_cm)
    return b


def test_return_home_traverses_and_completes_with_armed_body(monkeypatch):
    from rover.topo_map import TopoMap

    body = _armed_body(monkeypatch)
    monkeypatch.setattr(service, "body", body)
    monkeypatch.setattr(service, "movement_grant", None)

    # A 2-place graph: A (here) -> B (goal), with a forward edge.
    topo = TopoMap()
    a = topo.observe(sonar_sig=[100.0, 105.0, 110.0, 115.0, 120.0], now=1.0, name="office")
    b = topo.observe(sonar_sig=[40.0, 200.0, 35.0, 210.0, 30.0], last_node_id=a["node_id"], action="forward", now=2.0, name="dock")
    monkeypatch.setattr(service, "TOPO", topo)
    monkeypatch.setattr(service, "_last_topo_node", a["node_id"])

    async def fake_scan(zone, angles):
        return {"ok": True, "observations": []}, {"samples": [], "best": None, "center": None}

    monkeypatch.setattr(service, "reactive_escape_scan", fake_scan)
    # Relocalisation recognises the expected next place (B) on arrival.
    monkeypatch.setattr(topo, "recognize", lambda sig, hist, ir: SimpleNamespace(node_id=b["node_id"]))

    result = asyncio.run(service.return_home_task(goal=b["node_id"], allow_movement=True, max_hops=4, segment_cm=20.0, duration_seconds=20))
    assert result["ok"] is True
    assert result["moved"] is True
    assert result["done"] is True
    assert body.hardware.drives > 0  # real motor commands were issued


def test_return_home_aborts_and_asks_for_help_when_lost(monkeypatch):
    from rover.topo_map import TopoMap

    body = _armed_body(monkeypatch)
    monkeypatch.setattr(service, "body", body)
    monkeypatch.setattr(service, "movement_grant", None)

    topo = TopoMap()
    a = topo.observe(sonar_sig=[100.0, 105.0, 110.0, 115.0, 120.0], now=1.0, name="office")
    b = topo.observe(sonar_sig=[40.0, 200.0, 35.0, 210.0, 30.0], last_node_id=a["node_id"], action="forward", now=2.0, name="dock")
    monkeypatch.setattr(service, "TOPO", topo)
    monkeypatch.setattr(service, "_last_topo_node", a["node_id"])

    async def fake_scan(zone, angles):
        return {"ok": True, "observations": []}, {"samples": [], "best": None, "center": None}

    monkeypatch.setattr(service, "reactive_escape_scan", fake_scan)
    # Never recognises the expected place -> should abort gracefully (no crash).
    monkeypatch.setattr(topo, "recognize", lambda sig, hist, ir: SimpleNamespace(node_id=None))

    result = asyncio.run(service.return_home_task(goal=b["node_id"], allow_movement=True, max_hops=6, segment_cm=20.0, duration_seconds=20))
    assert result["ok"] is True
    assert result["aborted"] is True  # gave up and (per code) raised a rescue interrupt


def test_armed_drive_still_blocked_by_close_obstacle(monkeypatch):
    # The safety floor holds on the armed path: a close front reading stops drive.
    body = _armed_body(monkeypatch, front_cm=10.0)  # inside the stop threshold
    monkeypatch.setattr(service, "body", body)
    grant = service.MovementPermissionCommand(task="t", allow_movement=True, duration_seconds=10).model_dump() | {"expires_at": 9e18, "active": True, "owner": "t"}
    monkeypatch.setattr(service, "movement_grant", grant)
    out = asyncio.run(service.guarded_drive(service.DriveCommand(linear=0.25, turn=0, duration_ms=200), require_permission=True))
    assert out["ok"] is False
    assert out["stopped"] is True
