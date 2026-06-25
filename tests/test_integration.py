"""End-to-end integration tests: do Pip's subsystems actually COMPOSE?

These cross >=3 subsystems each and guard the integration fixes from the audit
(arbiter uses the new limbs, battery estimator drives self-preservation, topo
pointer persists, grant ownership, honest disarmed state, config braking
invariant, unified health, clean lifecycle). All sim/TestClient.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from rover import battery as battery_mod
from rover import cruise as cruise_mod
from rover import service
from rover.arbiter import BEHAVIOR_RETURN_TO_CHARGER, arbitrate
from rover.config import RoverConfig, default_config_path
from rover.models import DriveCommand, TurretCommand
from rover.topo_map import TopoMap

client = TestClient(service.app)


# --- I-2: battery estimator drives arbiter self-preservation ------------------
def test_battery_critical_from_estimator_routes_to_return_to_charger(monkeypatch):
    service.BATTERY = battery_mod.BatteryEstimator(critical_v=6.6, low_debounce=3)
    service.body.state.stopped = True  # idle, so samples are trusted
    monkeypatch.setattr(service.body, "sensors", lambda: {"front_distance_cm": 200.0, "battery_percent": 8.0, "battery_voltage": 6.3, "errors": {}})
    ctx = None
    for _ in range(3):  # debounce: critical trips on the 3rd idle low sample
        ctx = service.arbiter_context()
    assert ctx["battery_recommendation"] == "charge_before_movement"
    assert arbitrate(ctx)["behavior"] == BEHAVIOR_RETURN_TO_CHARGER


def test_charging_suppresses_return_to_charger():
    ctx = {"battery_recommendation": "charge_before_movement", "battery_charging": True, "mode": "social", "awake": True}
    assert arbitrate(ctx)["behavior"] != BEHAVIOR_RETURN_TO_CHARGER  # docked => don't drive off


# --- I-1: arbiter self-preservation uses the topo traversal limb --------------
def test_return_to_charger_invokes_topo_navigator(monkeypatch):
    # Isolate the graph (TOPO is a shared singleton across tests).
    monkeypatch.setattr(service, "TOPO", TopoMap())
    node = service.TOPO.observe(sonar_sig=[100.0, 105.0, 110.0, 115.0, 120.0], now=1.0, name="charger")
    service.set_last_topo_node(node["node_id"])
    called = {}

    async def fake_return_home(*, goal="charger", allow_movement=False, **kw):
        called["goal"] = goal
        return {"ok": True, "done": True, "moved": False}

    monkeypatch.setattr(service, "return_home_task", fake_return_home)
    result = asyncio.run(service.behavior_return_to_charger(allow_movement=False))
    assert called.get("goal") == node["node_id"]  # matched node id (not the literal "charger")
    assert result["via"] == "topo"


# --- I-5: the current-place pointer persists (so return-home survives reboot) --
def test_last_topo_node_persists_to_store():
    service.set_last_topo_node("place-test-xyz")
    assert service.store.load_json("last_topo_node") == "place-test-xyz"
    # Clearing must also persist None (no stale place resurrected on restart).
    service.set_last_topo_node(None)
    assert service.store.load_json("last_topo_node") is None


# --- review BUG-5: a place taught as "dock" is still driven to (not just "charger")
def test_return_to_charger_matches_dock_named_node(monkeypatch):
    monkeypatch.setattr(service, "TOPO", TopoMap())  # only a "dock" node exists
    node = service.TOPO.observe(sonar_sig=[55.0, 60.0, 65.0, 70.0, 75.0], now=1.0, name="dock")
    service.set_last_topo_node(node["node_id"])
    called = {}

    async def fake_return_home(*, goal="charger", allow_movement=False, **kw):
        called["goal"] = goal
        return {"ok": True, "done": True, "moved": False}

    monkeypatch.setattr(service, "return_home_task", fake_return_home)
    result = asyncio.run(service.behavior_return_to_charger(allow_movement=False))
    assert result["via"] == "topo"
    assert called["goal"] == node["node_id"]  # matched node id, not the literal "charger"


# --- I-3: grant ownership so cruise yields to a foreign task -------------------
def test_grant_permits_ownership():
    assert cruise_mod.grant_permits({"active": True, "owner": "cruise"}, "cruise") is True
    assert cruise_mod.grant_permits({"active": True, "owner": "hallway-scout"}, "cruise") is False
    assert cruise_mod.grant_permits({"active": True}, "cruise") is True  # ownerless = allowed
    assert cruise_mod.grant_permits({"active": False, "owner": "cruise"}, "cruise") is False
    assert cruise_mod.grant_permits(None, "cruise") is False


# --- I-4: no live grant published while motors are disarmed --------------------
def test_disarmed_task_publishes_no_active_grant():
    client.post("/movement/revoke")
    r = client.post("/tasks/reactive-explore", json={"zone": "office", "allow_movement": True, "duration_seconds": 2, "max_cycles": 1})
    assert r.status_code == 200
    # In sim motors are disarmed, so the grant must NOT read as active.
    assert service.active_movement_grant() is None
    client.post("/movement/revoke")


# --- I-7: an owner's destination wish becomes a pursuable goal -----------------
def test_exploration_goal_becomes_formal_goal():
    service.clear_goal()
    # A help-free destination (a door/room transition correctly needs a human, so
    # those intentionally do NOT auto-pursue).
    service.pip_set_exploration_goal("desk", source="test")
    goal = service.active_goal()
    assert goal is not None
    assert goal.kind == "explore_zone" and goal.target == "desk"
    service.clear_goal()


# --- P-2: config braking invariant is validated -------------------------------
def test_all_config_profiles_satisfy_braking_invariant():
    for path in default_config_path().parent.glob("*.json"):
        RoverConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))  # must not raise


def test_bad_braking_config_is_rejected():
    with pytest.raises(ValueError):
        RoverConfig.model_validate({"safety": {"reflex_hard_cm": 10.0, "front_stop_distance_cm": 8.0}, "nav": {"cruise_coast_cm": 8.0, "cruise_margin_cm": 4.0}})


# --- P-1: one composite "is Pip OK?" view -------------------------------------
def test_health_composite_is_one_coherent_view():
    data = client.get("/health/composite").json()
    assert data["ok"] is True
    for key in ("ready_to_move", "blockers", "battery", "feelings", "movement", "goal", "arbiter", "nav", "subsystems", "identity"):
        assert key in data
    assert "would_choose" in data["arbiter"]
    assert "soc_percent" in data["battery"]
    assert "version" in data["identity"]
    # In sim, motors are disarmed -> not ready, and that reason is surfaced.
    assert data["ready_to_move"] is False
    assert any("motor" in b.lower() for b in data["blockers"])


# --- D: a full heartbeat touches battery + mood + persistence -----------------
def test_full_heartbeat_touches_battery_and_state():
    out = service.life_heartbeat_step()
    assert out["ok"] is True
    assert "feelings" in out
    assert service._last_battery is not None  # update_battery ran


# --- J: advisory layers never relax the reflex floor (safety regression) ------
def test_reflex_authority_holds_under_panned_turret(monkeypatch):
    import rover.drivers as drivers
    from rover.config import RoverConfig as RC

    class DummyHW:
        def __init__(self, config):
            pass

        def stop(self):
            pass

        def drive(self, command):
            pass

    monkeypatch.setattr(drivers, "FreenoveHardware", DummyHW)
    b = drivers.RoverBody(mode="hardware", config=RC.model_validate({"safety": {"bench_safe_no_motors": False}}))
    b.state.turret = TurretCommand(pan_deg=60.0)  # sonar pointed away
    monkeypatch.setattr(b, "_sensor_snapshot", lambda: {"front_distance_cm": 300.0, "line_sensors": None, "bumpers": None})
    fired = asyncio.run(b._check_forward_reflex(DriveCommand(linear=0.3, turn=0, duration_ms=200), source="test"))
    assert fired is True  # forward refused despite a wide-open side reading
