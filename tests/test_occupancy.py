"""Tests for the rolling robot-centric log-odds occupancy grid."""

from __future__ import annotations

import math

import pytest

from rover.occupancy import (
    CELL_FREE,
    CELL_OCCUPIED,
    CELL_UNKNOWN,
    GridConfig,
    OccupancyGrid,
)


def test_config_rejects_even_or_tiny_size():
    with pytest.raises(ValueError):
        GridConfig(size_cells=40)
    with pytest.raises(ValueError):
        GridConfig(size_cells=3)


def test_fresh_grid_is_all_unknown():
    g = OccupancyGrid(config=GridConfig(size_cells=21, cell_cm=10.0))
    s = g.stats()
    assert s["unknown"] == 21 * 21
    assert s["free"] == 0 and s["occupied"] == 0
    # robot starts on the centre cell
    col, row = g.cell_of(g.x_cm, g.y_cm)
    assert (col, row) == (10, 10)


def test_ray_marks_free_then_occupied_at_range():
    g = OccupancyGrid(config=GridConfig(size_cells=41, cell_cm=10.0))
    # Obstacle 100cm straight ahead (heading 0 = +x).
    g.update_ray(0.0, 100.0)
    # A cell ~50cm ahead should read free; a cell ~100cm ahead should read occupied.
    near = g.cell_of(g.x_cm + 50.0, g.y_cm)
    hit = g.cell_of(g.x_cm + 100.0, g.y_cm)
    assert g.classify(*near) == CELL_FREE
    assert g.classify(*hit) == CELL_OCCUPIED
    # A cell well beyond the hit stays unknown (we don't see through walls).
    beyond = g.cell_of(g.x_cm + 160.0, g.y_cm)
    assert g.classify(*beyond) == CELL_UNKNOWN


def test_maxrange_reading_clears_free_but_never_marks_obstacle():
    g = OccupancyGrid(config=GridConfig(size_cells=41, cell_cm=10.0, z_max_cm=300.0))
    g.update_ray(0.0, None)  # no echo / open
    near = g.cell_of(g.x_cm + 80.0, g.y_cm)
    assert g.classify(*near) == CELL_FREE
    # Nothing in the cone should ever be occupied from a dropout.
    n = g.config.size_cells
    assert all(g.classify(c, r) != CELL_OCCUPIED for c in range(n) for r in range(n))


def test_stale_cell_self_heals_when_contradicted():
    g = OccupancyGrid(config=GridConfig(size_cells=41, cell_cm=10.0, l_clamp=2.0))
    for _ in range(8):
        g.update_ray(0.0, 100.0)  # build up an obstacle at 100cm
    hit = g.cell_of(g.x_cm + 100.0, g.y_cm)
    assert g.classify(*hit) == CELL_OCCUPIED
    # The obstacle moves away: now repeated open readings should clear it.
    for _ in range(8):
        g.update_ray(0.0, None)
    assert g.classify(*hit) != CELL_OCCUPIED  # tight clamp lets it forget


def test_recenter_keeps_robot_near_middle_and_preserves_nearby_cells():
    cfg = GridConfig(size_cells=41, cell_cm=10.0, recenter_margin_cells=5)
    g = OccupancyGrid(config=cfg)
    g.update_ray(0.0, 100.0)
    hit_local = (g.x_cm + 100.0, g.y_cm)
    # Drive forward 1m; this should trigger a recenter (>5 cells from middle... 10 cells).
    g.integrate_forward(100.0)
    rcol, rrow = g.cell_of(g.x_cm, g.y_cm)
    center = cfg.size_cells // 2
    assert abs(rcol - center) <= cfg.recenter_margin_cells
    assert abs(rrow - center) <= cfg.recenter_margin_cells
    # The obstacle we saw is still represented at its world location (now behind us).
    assert g.classify(*g.cell_of(*hit_local)) == CELL_OCCUPIED


def test_turn_then_ray_marks_correct_world_bearing():
    g = OccupancyGrid(config=GridConfig(size_cells=41, cell_cm=10.0))
    g.integrate_turn(90.0)  # now facing +y
    g.update_ray(0.0, 100.0)
    hit = g.cell_of(g.x_cm, g.y_cm + 100.0)
    assert g.classify(*hit) == CELL_OCCUPIED


def test_frontiers_returns_boundary_between_free_and_unknown():
    g = OccupancyGrid(config=GridConfig(size_cells=41, cell_cm=10.0))
    # Sweep a fan of open readings -> a wedge of free space whose far edge borders unknown.
    for bearing in range(-40, 41, 10):
        g.update_ray(float(bearing), 80.0)
    fr = g.frontiers(min_cluster=2)
    assert fr, "expected at least one frontier on the free/unknown boundary"
    # Frontiers are ranked nearest-first.
    dists = [f["distance_cm"] for f in fr]
    assert dists == sorted(dists)
    # The leading frontier should be roughly ahead (within the swept fan).
    assert any(abs(f["bearing_deg"]) <= 50 for f in fr)


def test_explored_fraction_grows_with_observation():
    g = OccupancyGrid(config=GridConfig(size_cells=41, cell_cm=10.0))
    before = g.stats()["explored_frac"]
    for bearing in range(-60, 61, 15):
        g.update_ray(float(bearing), 120.0)
    after = g.stats()["explored_frac"]
    assert after > before


def test_probability_monotonic_with_log_odds():
    g = OccupancyGrid(config=GridConfig(size_cells=21, cell_cm=10.0))
    col, row = g.cell_of(g.x_cm + 50.0, g.y_cm)
    p0 = g.probability(col, row)
    assert abs(p0 - 0.5) < 1e-9
    g.update_ray(0.0, 100.0)  # marks the 50cm cell free
    assert g.probability(col, row) < 0.5
