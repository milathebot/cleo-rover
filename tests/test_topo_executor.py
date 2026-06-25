"""Tests for the return-home topo-route executor (pure core)."""

from __future__ import annotations

from rover.topo_executor import ReturnState, edge_motions, plan_return, rotation_chunks
from rover.topo_map import TopoMap


def test_rotation_chunks_split_big_turns():
    # A 90deg turn must become two <=45deg pulses that sum to 90 (else truncated).
    chunks = rotation_chunks(90.0, max_step=45.0)
    assert all(abs(c) <= 45.0 for c in chunks)
    assert abs(sum(chunks) - 90.0) < 1e-6
    assert len(chunks) == 2
    assert rotation_chunks(180.0, max_step=45.0) == [45.0, 45.0, 45.0, 45.0]
    assert rotation_chunks(-90.0, max_step=45.0) == [-45.0, -45.0]
    assert rotation_chunks(0.0) == []
    assert rotation_chunks(20.0) == [20.0]


def test_single_node_route_is_already_done():
    st = ReturnState(path=["charger"], actions=[])  # already at the goal
    assert st.done is True
    assert st.expected_next is None


def test_edge_motions_turn_then_forward():
    m = edge_motions("turn_left", 0.0, segment_cm=50.0)
    assert m[0] == ("rotate", 90.0)
    assert m[-1] == ("forward", 50.0)


def test_edge_motions_forward_only_when_aligned():
    m = edge_motions("forward", 3.0, segment_cm=40.0)  # heading_out within deadband
    assert m == [("forward", 40.0)]


def test_edge_motions_uses_heading_out_when_significant():
    m = edge_motions("forward", 60.0, segment_cm=40.0)
    assert m[0][0] == "rotate"
    assert m[0][1] == 60.0


def test_return_state_advances_on_correct_observation():
    st = ReturnState(path=["a", "b", "c"], actions=[{"action": "forward"}, {"action": "forward"}])
    assert st.expected_next == "b"
    assert st.on_observed("b") == "advanced"
    assert st.expected_next == "c"
    assert st.on_observed("c") == "advanced"
    assert st.done is True


def test_return_state_retries_then_aborts_on_misses():
    st = ReturnState(path=["a", "b"], actions=[{"action": "forward"}], max_misses=3)
    assert st.on_observed("x") == "retry"
    assert st.on_observed(None) == "retry"
    assert st.on_observed("y") == "aborted"
    assert st.aborted is True


def test_correct_observation_resets_miss_counter():
    st = ReturnState(path=["a", "b", "c"], actions=[{"action": "forward"}, {"action": "forward"}], max_misses=3)
    st.on_observed("x")  # miss
    assert st.misses == 1
    st.on_observed("b")  # advance resets
    assert st.misses == 0


def test_plan_return_without_start_is_graceful():
    m = TopoMap()
    res = plan_return(m, None, "kitchen")
    assert res["ok"] is False
    assert "no current place" in res["reason"]


def test_plan_return_builds_route():
    m = TopoMap()
    a = m.observe(sonar_sig=[100.0, 105.0, 110.0, 115.0, 120.0], hist_desc=[1.0, 0.0], now=1.0, name="office")
    b = m.observe(sonar_sig=[40.0, 200.0, 35.0, 210.0, 30.0], last_node_id=a["node_id"], action="forward", now=2.0, name="dock")
    res = plan_return(m, a["node_id"], "dock")
    assert res["ok"] is True
    assert res["path"][0] == a["node_id"] and res["path"][-1] == b["node_id"]
