"""Tests for pure social-reaction logic."""

from __future__ import annotations

from rover.social import REACT_GREET, REACT_IGNORE, REACT_KEEP_DISTANCE, REACT_ORIENT, decide_social_reaction


def _react(**kw):
    base = dict(person_present=False, pet_present=False, bearing_bucket=None, distance_cm=None, seconds_since_greet=None, quiet=False)
    base.update(kw)
    return decide_social_reaction(**base)


def test_no_one_is_ignored():
    assert _react()["reaction"] == REACT_IGNORE


def test_fresh_person_is_greeted_and_oriented():
    r = _react(person_present=True, bearing_bucket="right", distance_cm=120)
    assert r["reaction"] == REACT_GREET
    assert r["turn_deg"] > 0
    assert r["speak"]


def test_quiet_hours_orient_without_greeting():
    r = _react(person_present=True, bearing_bucket="center", distance_cm=120, quiet=True)
    assert r["reaction"] == REACT_ORIENT
    assert r["speak"] is None


def test_recently_greeted_just_orients():
    r = _react(person_present=True, bearing_bucket="left", distance_cm=120, seconds_since_greet=5.0)
    assert r["reaction"] == REACT_ORIENT
    assert r["turn_deg"] < 0


def test_close_pet_keeps_distance():
    r = _react(pet_present=True, bearing_bucket="center", distance_cm=20.0)
    assert r["reaction"] == REACT_KEEP_DISTANCE
