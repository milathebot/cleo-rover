"""Tests for the PD wall-follower + corner handling."""

from __future__ import annotations

import pytest

from rover.wall_follow import (
    ACTION_FOLLOW,
    ACTION_INSIDE_CORNER,
    ACTION_OUTSIDE_CORNER,
    ACTION_SEARCH,
    WallFollowConfig,
    wall_follow_step,
)


def test_config_validates():
    with pytest.raises(ValueError):
        WallFollowConfig(setpoint_cm=0.0)


def test_on_setpoint_drives_straight():
    d = wall_follow_step(side_cm=25.0, front_cm=None, prev_error_cm=None, side="left")
    assert d.action == ACTION_FOLLOW
    assert d.turn == 0.0
    assert d.linear > 0


def test_too_far_left_wall_steers_left_toward_wall():
    d = wall_follow_step(side_cm=45.0, front_cm=None, prev_error_cm=0.0, side="left")
    assert d.action == ACTION_FOLLOW
    assert d.turn > 0  # +turn = left = toward the left wall


def test_too_close_left_wall_steers_right_away():
    d = wall_follow_step(side_cm=10.0, front_cm=None, prev_error_cm=0.0, side="left")
    assert d.turn < 0  # steer away from the wall


def test_right_wall_mirror_sign():
    far = wall_follow_step(side_cm=45.0, front_cm=None, prev_error_cm=0.0, side="right")
    assert far.turn < 0  # too far from a RIGHT wall => steer right (negative)


def test_inside_corner_pivots_away_and_stops():
    d = wall_follow_step(side_cm=25.0, front_cm=20.0, prev_error_cm=0.0, side="left")
    assert d.action == ACTION_INSIDE_CORNER
    assert d.linear == 0.0
    assert d.turn < 0  # pivot away from the left wall (i.e. right)


def test_outside_corner_rounds_toward_wall():
    cfg = WallFollowConfig(setpoint_cm=25.0, outside_corner_jump_cm=40.0, lost_wall_cm=150.0)
    d = wall_follow_step(side_cm=80.0, front_cm=None, prev_error_cm=0.0, side="left", cfg=cfg)
    assert d.action == ACTION_OUTSIDE_CORNER
    assert d.turn > 0  # curve back toward the (left) wall
    assert d.linear > 0


def test_lost_wall_searches():
    d = wall_follow_step(side_cm=None, front_cm=None, prev_error_cm=None, side="left")
    assert d.action == ACTION_SEARCH
    assert d.error_cm is None
    assert d.linear > 0


def test_inside_corner_takes_priority_over_pd():
    # Even when the side error is large, a wall ahead must win.
    d = wall_follow_step(side_cm=60.0, front_cm=15.0, prev_error_cm=0.0, side="left")
    assert d.action == ACTION_INSIDE_CORNER


def test_turn_is_clamped_to_max():
    cfg = WallFollowConfig(max_turn=0.4)
    d = wall_follow_step(side_cm=200.0 - 80.0, front_cm=None, prev_error_cm=-1000.0, side="left", cfg=cfg)
    assert abs(d.turn) <= 0.4 + 1e-9
