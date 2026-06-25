"""Tests for the continuous-perception PolarSnapshot + weave schedule."""

from __future__ import annotations

from rover.perception import Cell, PolarSnapshot, weave_schedule


def test_weave_puts_forward_every_other_slot():
    sched = weave_schedule([-20, 20, -45, 45])
    assert sched == [0, -20, 0, 20, 0, -45, 0, 45]
    # 0deg appears on every even index -> refreshed every 2 slots.
    assert all(sched[i] == 0 for i in range(0, len(sched), 2))


def test_weave_empty_falls_back_to_forward():
    assert weave_schedule([]) == [0]


def test_snapshot_freshness_and_age():
    s = PolarSnapshot()
    s.update(0.0, 120.0, now=100.0)
    assert s.fresh(0.0, max_age_ms=700, now=100.3) is True   # 300ms old
    assert s.fresh(0.0, max_age_ms=700, now=101.0) is False  # 1000ms old
    assert s.age_ms(0.0, now=100.5) == 500.0
    assert s.fresh(60.0, max_age_ms=700, now=100.1) is False  # never seen


def test_fwd_cone_min_distance_and_worst_age():
    s = PolarSnapshot()
    s.update(0.0, 100.0, now=100.0)
    s.update(15.0, 60.0, now=100.0)   # within cone, closer
    s.update(70.0, 30.0, now=100.0)   # outside cone, ignored
    min_cm, worst_age = s.fwd_cone(now=100.5, half_deg=20.0, max_age_ms=700)
    assert min_cm == 60.0
    assert worst_age == 500.0


def test_fwd_cone_unseen_is_infinite_age():
    s = PolarSnapshot()
    min_cm, worst_age = s.fwd_cone(now=100.0, half_deg=20.0, max_age_ms=700)
    assert min_cm is None
    assert worst_age == float("inf")  # dead/never-run producer -> consumer must stop


def test_fwd_cone_stale_cell_not_counted_as_min_but_ages():
    s = PolarSnapshot()
    s.update(0.0, 100.0, now=100.0)
    min_cm, worst_age = s.fwd_cone(now=101.0, half_deg=20.0, max_age_ms=700)  # 1000ms old
    assert min_cm is None         # too stale to trust as a clearance
    assert worst_age == 1000.0    # but its staleness is reported -> triggers a stop


def test_vfh_samples_drops_stale_cells():
    s = PolarSnapshot()
    s.update(-20.0, 100.0, now=100.0)
    s.update(0.0, 90.0, now=100.0)
    s.update(20.0, 80.0, now=98.0)   # 2s old at now=100 -> dropped (>1500ms)
    samples = s.vfh_samples(now=100.0, max_age_ms=1500)
    bearings = [b for b, _ in samples]
    assert -20.0 in bearings and 0.0 in bearings
    assert 20.0 not in bearings
