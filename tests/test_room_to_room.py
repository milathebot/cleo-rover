"""Room-to-room roaming + place-aware memory.

Pip has no encoders/IMU/LiDAR; room-to-room rides on the topological place graph
(relocalise per place) + a closed baby gate + the cliff reflex as the real safety.
These tests lock in the wiring: current_zone tracks recognised named places, the
soft zone gate lifts only when cross-zone roaming is on, rooms can be taught + named,
roaming is biased toward interesting rooms, and recall works per-room.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from rover import explore
from rover.models import SpatialMemoryItem
from rover.service import (
    CONFIG,
    TOPO,
    app,
    destination_requires_help,
    name_current_place,
    parse_place_label,
    parse_zone_query,
    pip_can_autonomously_move,
    pip_state,
    set_last_topo_node,
    sync_current_zone_to_place,
    zone_memory_summary,
)

client = TestClient(app)


# --- place-interest scoring (pure) ----------------------------------------
def test_place_interest_rewards_recent_pet_sightings():
    now = 1_000_000.0
    items = [
        SpatialMemoryItem(id="a", label="cat", kind="vision_pet", zone="kitchen", last_seen_at=now - 60),
        SpatialMemoryItem(id="b", label="wall", kind="vision_obstacle", zone="office", last_seen_at=now - 60),
    ]
    scores = explore.place_interest(items, now=now)
    assert scores["kitchen"] > 0.5
    assert scores.get("office", 0.0) <= 0.0  # an obstacle is not a draw


def test_place_interest_decays_with_age():
    now = 1_000_000.0
    fresh = explore.place_interest([SpatialMemoryItem(id="a", label="cat", kind="vision_pet", zone="z", last_seen_at=now - 60)], now=now)
    stale = explore.place_interest([SpatialMemoryItem(id="a", label="cat", kind="vision_pet", zone="z", last_seen_at=now - 5 * 86400)], now=now)
    assert fresh["z"] > stale["z"]


# --- current_zone follows recognised named places -------------------------
def test_sync_current_zone_only_follows_named_places():
    saved_zone = pip_state.get("current_zone")
    saved_keys = set(TOPO.nodes)
    saved_last = None
    try:
        named = TOPO.add_node(sonar_sig=[100.0, 100.0, 100.0], name="kitchen")
        anon = TOPO.add_node(sonar_sig=[80.0, 80.0, 80.0])  # auto-named "place-N"
        pip_state["current_zone"] = "office"
        # An anonymous place must NOT change which room Pip thinks it's in.
        sync_current_zone_to_place(anon.id)
        assert pip_state["current_zone"] == "office"
        # A taught/named place does.
        sync_current_zone_to_place(named.id)
        assert pip_state["current_zone"] == "kitchen"
    finally:
        for nid in list(TOPO.nodes):
            if nid not in saved_keys:
                del TOPO.nodes[nid]
        pip_state["current_zone"] = saved_zone
        set_last_topo_node(saved_last)


# --- teaching a room name -------------------------------------------------
def test_name_current_place_renames_node_and_sets_zone():
    saved_zone = pip_state.get("current_zone")
    saved_keys = set(TOPO.nodes)
    try:
        node = TOPO.add_node(sonar_sig=[120.0, 90.0, 120.0], name="office")
        set_last_topo_node(node.id)
        res = name_current_place("the kitchen")
        assert res["ok"] and res["node"] == node.id
        assert TOPO.nodes[node.id].name == "kitchen"  # 'the ' stripped, lowercased
        assert pip_state["current_zone"] == "kitchen"
    finally:
        for nid in list(TOPO.nodes):
            if nid not in saved_keys:
                del TOPO.nodes[nid]
        pip_state["current_zone"] = saved_zone
        set_last_topo_node(None)


# --- the soft zone gate lifts only when roaming is enabled ----------------
def test_cross_zone_gate_blocks_then_lifts():
    saved = {k: pip_state.get(k) for k in ("mode", "awake", "current_zone")}
    saved_flag = CONFIG.nav.cross_zone_roam_enabled
    try:
        pip_state["mode"] = "social"
        pip_state["awake"] = True
        pip_state["current_zone"] = "hallway"  # not in approved_zones (["office"])
        ok_batt = {"recommendation": "ok"}
        CONFIG.nav.cross_zone_roam_enabled = False
        ok, reason = pip_can_autonomously_move(allow_movement=True, battery=ok_batt)
        assert ok is False and "zone" in reason
        CONFIG.nav.cross_zone_roam_enabled = True
        ok, _ = pip_can_autonomously_move(allow_movement=True, battery=ok_batt)
        assert ok is True
    finally:
        CONFIG.nav.cross_zone_roam_enabled = saved_flag
        for k, v in saved.items():
            pip_state[k] = v


# --- destinations: stairs always need help; rooms only when roaming off ---
def test_destination_help_policy():
    saved = CONFIG.nav.cross_zone_roam_enabled
    try:
        CONFIG.nav.cross_zone_roam_enabled = False
        assert destination_requires_help("kitchen") is True
        assert destination_requires_help("downstairs") is True
        CONFIG.nav.cross_zone_roam_enabled = True
        assert destination_requires_help("kitchen") is False  # roaming allowed
        assert destination_requires_help("downstairs") is True  # stairs never auto
        assert destination_requires_help("the backyard") is True  # outdoors never auto
    finally:
        CONFIG.nav.cross_zone_roam_enabled = saved


# --- voice parsers --------------------------------------------------------
def test_parse_place_label():
    assert parse_place_label("this room is the kitchen") == "kitchen"
    assert parse_place_label("remember this place as the living room") == "living room"
    assert parse_place_label("you are now in the hallway") == "hallway"
    assert parse_place_label("what a nice day") is None


def test_parse_zone_query():
    assert parse_zone_query("what's in the kitchen") == "kitchen"
    assert parse_zone_query("what did you see in the office") == "office"
    assert parse_zone_query("hello there") is None


# --- recall ---------------------------------------------------------------
def test_zone_memory_summary_empty_and_populated():
    empty = zone_memory_summary("nowhere-xyz")
    assert "don't have any memories" in empty["line"]
    # Teach a sighting in a unique test zone, then recall it.
    client.post("/map/remember", json={"id": "rtr-cat-1", "label": "cat", "kind": "vision_pet", "zone": "rtr-testroom", "last_seen_at": time.time()})
    recall = client.get("/map/zone/rtr-testroom").json()
    assert recall["ok"] is True
    assert "cat" in recall["line"].lower()


def test_voice_command_names_a_room():
    saved_zone = pip_state.get("current_zone")
    saved_keys = set(TOPO.nodes)
    try:
        node = TOPO.add_node(sonar_sig=[100.0, 100.0, 100.0], name="office")
        set_last_topo_node(node.id)
        r = client.post("/pip/command", json={"text": "this room is the studio", "source": "test"})
        data = r.json()
        assert data["action"] == "name_place"
        assert pip_state["current_zone"] == "studio"
    finally:
        for nid in list(TOPO.nodes):
            if nid not in saved_keys:
                del TOPO.nodes[nid]
        pip_state["current_zone"] = saved_zone
        set_last_topo_node(None)
