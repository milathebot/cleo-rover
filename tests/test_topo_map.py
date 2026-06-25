"""Tests for the topological place-graph."""

from __future__ import annotations

from rover.topo_map import (
    TopoMap,
    hist_similarity,
    sonar_signature_match,
)


def test_sonar_signature_match_fraction():
    a = [100.0, 80.0, 120.0, 60.0, 90.0]
    b = [102.0, 79.0, 118.0, 61.0, 130.0]  # last beam disagrees
    score = sonar_signature_match(a, b, tol=0.1)
    assert 0.7 < score < 0.85  # 4 of 5 agree


def test_sonar_match_ignores_out_of_range():
    a = [100.0, 300.0, 120.0, 300.0]  # two beams out of range
    b = [101.0, 300.0, 119.0, 300.0]
    # Only 2 comparable beams -> below the 4-beam floor -> 0.0 (not enough signal).
    assert sonar_signature_match(a, b) == 0.0


def test_hist_similarity_cosine():
    assert hist_similarity([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == 1.0
    assert hist_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert hist_similarity([], [1.0]) is None


def _sig(base):
    return [base + i for i in (0, 5, 10, 15, 20)]


def test_observe_adds_then_recognizes_same_place():
    m = TopoMap()
    sig = _sig(100.0)
    r1 = m.observe(sonar_sig=sig, hist_desc=[1.0, 0.0, 0.0], now=1.0, name="office")
    assert r1["event"] == "added"
    # Same place again (slightly noisy) -> recognized + relocalized, no new node.
    noisy = [v + 1.0 for v in sig]
    r2 = m.observe(sonar_sig=noisy, hist_desc=[0.99, 0.01, 0.0], now=2.0)
    assert r2["event"] == "recognized"
    assert r2["relocalized"] is True
    assert len(m.nodes) == 1
    assert m.nodes[r1["node_id"]].visits == 2


def test_distinct_places_make_distinct_nodes_and_edge():
    m = TopoMap()
    a = m.observe(sonar_sig=_sig(100.0), hist_desc=[1.0, 0.0, 0.0], now=1.0, name="office")
    b = m.observe(
        sonar_sig=[40.0, 200.0, 35.0, 210.0, 30.0],
        hist_desc=[0.0, 1.0, 0.0],
        last_node_id=a["node_id"],
        action="forward",
        now=2.0,
        name="hallway",
    )
    assert b["event"] == "added"
    assert len(m.nodes) == 2
    assert len(m.edges) == 1
    assert m.edges[0].src == a["node_id"] and m.edges[0].dst == b["node_id"]


def test_plan_route_by_name():
    m = TopoMap()
    a = m.observe(sonar_sig=_sig(100.0), hist_desc=[1.0, 0.0], now=1.0, name="office")
    b = m.observe(sonar_sig=[40.0, 200.0, 35.0, 210.0, 30.0], hist_desc=[0.0, 1.0], last_node_id=a["node_id"], action="forward", now=2.0, name="hallway")
    c = m.observe(sonar_sig=[300.0, 50.0, 300.0, 55.0, 300.0], hist_desc=[0.5, 0.5], last_node_id=b["node_id"], action="turn_left", now=3.0, name="kitchen")
    plan = m.plan(a["node_id"], "kitchen")
    assert plan["ok"] is True
    assert plan["path"] == [a["node_id"], b["node_id"], c["node_id"]]
    assert [step["action"] for step in plan["actions"]] == ["forward", "turn_left"]


def test_plan_unknown_goal_fails_gracefully():
    m = TopoMap()
    a = m.observe(sonar_sig=_sig(100.0), now=1.0, name="office")
    plan = m.plan(a["node_id"], "narnia")
    assert plan["ok"] is False
    assert plan["actions"] == []


def test_merge_duplicates_fuses_ghost_nodes():
    m = TopoMap(min_votes=3)  # force a duplicate by making recognition strict
    sig = _sig(100.0)
    a = m.observe(sonar_sig=sig, hist_desc=[1.0, 0.0], now=1.0, name="office")
    # Strict min_votes=3 with no IR context => the second observation can't reach
    # 3 votes, so it spawns a near-duplicate node.
    b = m.observe(sonar_sig=[v + 1.0 for v in sig], hist_desc=[1.0, 0.0], now=2.0)
    assert b["event"] == "added"
    assert len(m.nodes) == 2
    merged = m.merge_duplicates()
    assert merged == 1
    assert len(m.nodes) == 1


def test_roundtrip_serialization():
    m = TopoMap()
    a = m.observe(sonar_sig=_sig(100.0), hist_desc=[1.0, 0.0], now=1.0, name="office")
    m.observe(sonar_sig=[40.0, 200.0, 35.0, 210.0, 30.0], last_node_id=a["node_id"], now=2.0, name="hall")
    data = m.to_dict()
    m2 = TopoMap.from_dict(data)
    assert len(m2.nodes) == 2
    assert len(m2.edges) == 1
    assert m2.node_by_name("office") is not None
