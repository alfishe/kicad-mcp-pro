"""The stitched escape stub must actually meet the routed run.

``_escape_point`` works in millimetres and can land *between* two nodes of the
lattice the router searches on, while ``SchematicRouter`` quantises every node it
visits with ``round(point / grid_mm)``.  The stub used to be stitched to the raw
landing, leaving it short of the run by a fraction of a grid step: the finished
polyline had four free ends, which renders exactly like a route while being an
open wire.

KiCad pins usually sit on the 1.27 mm grid, so this never showed up on a real
board -- that was luck of the standard rather than a guarantee in the code, and
it stopped being luck the moment a pin sat off-grid.
"""

from __future__ import annotations

from kicad_mcp.tools.schematic import BBox, _route_avoiding_obstacles

_EPS = 1e-6
_Segment = tuple[float, float, float, float]


def _count_free_ends(segments: list[_Segment]) -> list[tuple[float, float]]:
    """Endpoints that no other segment shares.

    A connected run of segments is a chain: every interior vertex is used twice
    and exactly two ends are used once.  Counting odd-degree endpoints is the
    cheapest way to say "this is one wire", and it catches the failure mode where
    a stitched stub and the routed run never actually meet.
    """
    used: dict[tuple[float, float], int] = {}
    for x1, y1, x2, y2 in segments:
        for point in ((round(x1, 4), round(y1, 4)), (round(x2, 4), round(y2, 4))):
            used[point] = used.get(point, 0) + 1
    return [point for point, count in used.items() if count % 2]


def _assert_single_chain(segments: list[_Segment]) -> None:
    """A route must be one connected polyline, not a scattering of segments."""
    free_ends = _count_free_ends(segments)
    assert len(free_ends) == 2, (
        f"route is not a single connected run: {len(free_ends)} free ends at {free_ends}"
    )


def test_route_is_connected_for_a_pin_off_the_router_grid() -> None:
    """An off-grid pin must still yield one connected Manhattan run.

    Coordinates are deliberately not multiples of 1.27 mm: the pin at (10.0,
    12.0) escapes to (8.73, 12.0), which is between the nodes at x=8.89 and
    x=10.16.  Stitching to that raw landing is what used to leave the wire open.
    """
    segments, warning = _route_avoiding_obstacles(
        (10.0, 12.0),
        (12.0, 4.0),
        [BBox(10.0, 10.0, 14.0, 14.0)],
        False,
        None,
    )

    assert warning is None
    _assert_single_chain(segments)
    assert not [
        segment
        for segment in segments
        if abs(segment[0] - segment[2]) > _EPS and abs(segment[1] - segment[3]) > _EPS
    ], f"diagonal segment in a Manhattan run: {segments}"


def test_route_is_connected_for_an_off_grid_pin_when_snapping_is_enabled() -> None:
    """Snapping the landing rather than the stub is not enough on its own.

    ``snap_to_grid`` moves the *landing* onto the lattice, which fixes the meeting
    point but bends the stub off the axis it left along.  The stub is finished as
    an L either way, so both settings give the same connected Manhattan run.
    """
    segments, warning = _route_avoiding_obstacles(
        (10.0, 12.0),
        (12.0, 4.0),
        [BBox(10.0, 10.0, 14.0, 14.0)],
        True,
        None,
    )

    assert warning is None
    _assert_single_chain(segments)
    assert not [
        segment
        for segment in segments
        if abs(segment[0] - segment[2]) > _EPS and abs(segment[1] - segment[3]) > _EPS
    ], f"diagonal segment in a Manhattan run: {segments}"


def test_route_is_connected_when_both_ends_are_off_grid() -> None:
    """Two off-grid pins, one run: the invariant is not about the start alone."""
    segments, warning = _route_avoiding_obstacles(
        (3.05, 2.03),
        (11.11, 8.07),
        [BBox(3.05, 2.03, 6.0, 5.0), BBox(11.11, 8.07, 14.0, 11.0)],
        False,
        None,
    )

    assert warning is None
    _assert_single_chain(segments)
