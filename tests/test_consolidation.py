"""Tests for episodic->semantic memory consolidation."""

from __future__ import annotations

from rover.consolidation import (
    ConsolidationConfig,
    Fact,
    consolidate,
    decay,
    facts_from_dicts,
    facts_to_dicts,
    reinforce,
)

NOW = 1_000_000.0


def _ep(label, zone, *, ts=NOW, bearing=None, conf=0.6):
    return {"label": label, "zone": zone, "timestamp": ts, "bearing_deg": bearing, "confidence": conf}


def test_decay_halves_at_half_life():
    assert decay(0.8, 0) == 0.8
    assert 0.39 < decay(0.8, ConsolidationConfig().half_life_s) < 0.41


def test_reinforce_has_diminishing_returns():
    c = 0.5
    c1 = reinforce(c)
    c2 = reinforce(c1)
    assert c1 > c
    assert (c2 - c1) < (c1 - c)  # smaller step each time
    assert c2 <= 1.0


def test_promotion_requires_enough_observations():
    cfg = ConsolidationConfig(promote_n=3)
    # Only 2 sightings -> not promoted yet.
    eps = [_ep("charger", "office"), _ep("charger", "office")]
    res = consolidate(eps, [], now=NOW, cfg=cfg)
    assert res["promoted"] == 0
    assert res["fact_count"] == 0
    # A third sighting -> promoted to a fact.
    eps.append(_ep("charger", "office"))
    res = consolidate(eps, [], now=NOW, cfg=cfg)
    assert res["promoted"] == 1
    fact = res["facts"][0]
    assert fact.subject == "charger" and fact.object == "office"
    assert fact.predicate == "located_in"


def test_reinforce_existing_fact_bumps_confidence():
    f = Fact(subject="charger", predicate="located_in", object="office", confidence=0.5, observations=3, last_seen_at=NOW)
    res = consolidate([_ep("charger", "office")], [f], now=NOW)
    assert res["reinforced"] == 1
    assert res["facts"][0].confidence > 0.5
    assert res["facts"][0].observations == 4


def test_stale_low_confidence_fact_is_pruned():
    cfg = ConsolidationConfig(prune_conf=0.15)
    old = Fact(subject="cat", predicate="located_in", object="hall", confidence=0.3, observations=3, last_seen_at=NOW - 6 * cfg.half_life_s)
    res = consolidate([], [old], now=NOW, cfg=cfg)
    assert res["pruned"] == 1
    assert res["fact_count"] == 0


def test_old_episodes_are_discarded():
    cfg = ConsolidationConfig(episode_max_age_s=3600.0)
    fresh = _ep("charger", "office", ts=NOW)
    stale = _ep("charger", "office", ts=NOW - 7200.0)
    res = consolidate([fresh, stale], [], now=NOW, cfg=cfg)
    assert len(res["kept_episodes"]) == 1
    assert res["kept_episodes"][0]["timestamp"] == NOW


def test_detail_summarizes_bearing_side():
    cfg = ConsolidationConfig(promote_n=2)
    eps = [_ep("charger", "office", bearing=-40), _ep("charger", "office", bearing=-35)]
    res = consolidate(eps, [], now=NOW, cfg=cfg)
    assert "left" in res["facts"][0].detail


def test_facts_roundtrip_dicts():
    facts = [Fact(subject="charger", predicate="located_in", object="office", confidence=0.7, observations=5, last_seen_at=NOW)]
    rows = facts_to_dicts(facts)
    back = facts_from_dicts(rows)
    assert back[0].subject == "charger"
    assert back[0].confidence == 0.7


def test_episodes_missing_place_are_ignored():
    res = consolidate([{"label": "charger"}], [], now=NOW)
    assert res["fact_count"] == 0
