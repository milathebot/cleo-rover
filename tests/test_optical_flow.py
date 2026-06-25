"""Tests for the pure optical-flow motion/stall/yaw/looming decision logic."""

from __future__ import annotations

from rover.vision_service import FlowConfig, FlowState, StallConfirmer, flow_motion_state


def _grid(n=20, w=320, h=240):
    pts = []
    for i in range(n):
        pts.append((float((i * 37) % w), float((i * 53) % h)))
    return pts


def test_too_few_tracks_is_unknown_not_stalled():
    pts = [(10.0, 10.0), (20.0, 20.0)]
    s = flow_motion_state(pts, pts, cmd_linear=0.3)
    assert s.moving is None
    assert s.stalled is False
    assert "unknown" in s.note


def test_static_image_while_commanded_is_a_stall():
    pts = _grid()
    s = flow_motion_state(pts, pts, cmd_linear=0.3)  # zero flow but commanded forward
    assert s.moving is False
    assert s.stalled is True


def test_static_image_without_command_is_not_a_stall():
    pts = _grid()
    s = flow_motion_state(pts, pts, cmd_linear=0.0)
    assert s.stalled is False


def test_clear_translation_reads_as_moving():
    prev = _grid()
    cur = [(x + 5.0, y) for x, y in prev]  # uniform 5px shift
    s = flow_motion_state(prev, cur, cmd_linear=0.3)
    assert s.moving is True
    assert s.stalled is False
    assert s.median_flow_px >= 4.0


def test_yaw_sign_from_horizontal_flow():
    prev = _grid()
    # Scene shifts right => robot turned left (CCW) => yaw_sign +1.
    cur_right = [(x + 6.0, y) for x, y in prev]
    assert flow_motion_state(prev, cur_right).yaw_sign == 1
    cur_left = [(x - 6.0, y) for x, y in prev]
    assert flow_motion_state(prev, cur_left).yaw_sign == -1


def test_looming_ttc_from_diverging_flow():
    # Build a field diverging from the image centre (approaching a wall).
    cx, cy = 160.0, 120.0
    prev, cur = [], []
    for ang in range(0, 360, 20):
        import math

        r = 90.0
        px, py = cx + r * math.cos(math.radians(ang)), cy + r * math.sin(math.radians(ang))
        prev.append((px, py))
        # push each point outward by 8% (expansion)
        cur.append((cx + (px - cx) * 1.08, cy + (py - cy) * 1.08))
    s = flow_motion_state(prev, cur, cmd_linear=0.3, img_w=320, img_h=240)
    assert s.moving is True
    assert s.ttc_frames is not None
    assert s.ttc_frames > 0


def test_no_ttc_when_turning():
    prev = _grid()
    cur = [(x + 6.0, y) for x, y in prev]  # pure horizontal => turning
    s = flow_motion_state(prev, cur, cmd_linear=0.3)
    assert s.yaw_sign != 0
    assert s.ttc_frames is None  # looming only valid when going roughly straight


def test_stall_confirmer_needs_consecutive_frames():
    cfg = FlowConfig(stall_hysteresis=3)
    conf = StallConfirmer(cfg)
    stalled = FlowState(moving=False, stalled=True, median_flow_px=0.0, yaw_sign=0, yaw_rate_proxy=0.0, ttc_frames=None, n_tracks=20, note="")
    moving = FlowState(moving=True, stalled=False, median_flow_px=5.0, yaw_sign=0, yaw_rate_proxy=0.0, ttc_frames=None, n_tracks=20, note="")
    assert conf.update(stalled) is False
    assert conf.update(stalled) is False
    assert conf.update(stalled) is True  # third consecutive => confirmed
    assert conf.update(moving) is False  # resets
    assert conf.streak == 0
