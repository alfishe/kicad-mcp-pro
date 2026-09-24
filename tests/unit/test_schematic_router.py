from __future__ import annotations

from kicad_mcp.utils.schematic_router import RouterBBox, SchematicRouter


def test_schematic_router_routes_straight_line_without_obstacles() -> None:
    router = SchematicRouter(grid_mm=2.54)

    assert router.route((0.0, 0.0), (7.62, 0.0)) == [(0.0, 0.0, 7.62, 0.0)]


def test_schematic_router_bypasses_obstacle() -> None:
    router = SchematicRouter(
        grid_mm=2.54,
        obstacles=[RouterBBox(2.0, -1.0, 6.0, 1.0)],
        max_steps=300,
    )

    segments = router.route((0.0, 0.0), (10.16, 0.0))

    assert segments is not None
    assert len(segments) >= 3
    assert all(not (2.0 <= x1 <= 6.0 and -1.0 <= y1 <= 1.0) for x1, y1, _, _ in segments)


def test_schematic_router_returns_none_when_bend_budget_is_too_small() -> None:
    router = SchematicRouter(
        grid_mm=2.54,
        obstacles=[RouterBBox(2.0, -1.0, 6.0, 1.0)],
        max_steps=80,
    )

    assert router.route((0.0, 0.0), (10.16, 0.0), max_bends=0) is None


def test_route_avoiding_obstacles_escape_and_route() -> None:
    from kicad_mcp.tools.schematic import BBox, _route_avoiding_obstacles

    obs_r1 = BBox(49.53, 57.15, 52.07, 64.77)
    obs_c1 = BBox(77.47, 57.15, 82.55, 64.77)
    obs_r2 = BBox(107.95, 57.15, 110.49, 64.77)

    segments, warning = _route_avoiding_obstacles(
        start=(50.8, 57.15),
        end=(109.22, 57.15),
        obstacles=[obs_r1, obs_c1, obs_r2],
        snap_to_grid=True,
    )

    assert warning is None
    assert len(segments) >= 3
    # Wire must detour cleanly over or under C1 without cutting through C1:
    assert any(s[1] < 57.15 or s[1] > 64.77 for s in segments)

