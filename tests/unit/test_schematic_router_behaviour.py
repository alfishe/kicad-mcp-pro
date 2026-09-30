"""Routing-behaviour tests: one rule per test, on a bare grid.

Every rule here was measured on a real sheet before it was coded -- the 2-grid
bundle pitch, the 2-grid module-boundary clearance, the refusals to run along or
turn on a foreign wire -- so each test is a regression guard on an evidenced
decision rather than a restatement of whatever the code currently does.

Coordinates are grid steps: ``grid_mm=1.0``, so "2 grid" in a comment is ``2.0``
in the fixture, and a length in the fixture is a length in grid steps.

The rules fall into groups:

* leaving and arriving -- a wire leaves a pin along its outward normal and
  arrives against the far pin's, so neither end turns across the grain;
* foreign geometry -- another net's wire may be crossed but never run along,
  turned on, or landed on, because each of those makes KiCad union two nets;
* crossing policy -- crossings stay legal, and stay priced;
* bundle pitch -- 1 grid apart is never drawn, 2 grid is the pitch;
* module boundaries -- a hierarchical sheet or a drawn rectangle gets 2 grid of
  clearance for *parallel* runs, and is still crossed perpendicularly to reach
  the pins inside it;
* junction lifetime -- a dot lives exactly as long as a wire ends on it.
"""

from __future__ import annotations

import pytest

from kicad_mcp.schematic.sheet_pins import outward_normal_for_rotation
from kicad_mcp.tools.schematic import (
    BBox,
    _route_avoiding_obstacles,
)
from kicad_mcp.utils.schematic_router import (
    CROSSING_PENALTY,
    RouterBBox,
    SchematicRouter,
    hugs_boundary,
    module_boundary_edges,
)

_EPS = 1e-6
_Segment = tuple[float, float, float, float]

#: One grid step, in fixture units.  ``grid_mm=1.0`` makes the fixtures read in
#: grid steps, so every distance below is also the count of grid steps it spans.
_GRID = 1.0


def _route(
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    occupied: list[_Segment] | None = None,
    obstacles: list[RouterBBox] | None = None,
    boundaries: list[RouterBBox] | None = None,
    max_bends: int = 12,
    crossing_penalty: float | None = None,
) -> list[_Segment]:
    """Route on the bare grid, failing loudly rather than returning ``None``."""
    router = SchematicRouter(
        grid_mm=_GRID,
        obstacles=obstacles,
        occupied=occupied,
        boundaries=boundaries,
        **({} if crossing_penalty is None else {"crossing_penalty": crossing_penalty}),
    )
    segments = router.route(start, end, max_bends=max_bends)
    assert segments is not None, f"no route from {start} to {end}"
    return segments


def _direction(segment: _Segment) -> tuple[int, int]:
    x1, y1, x2, y2 = segment
    return (
        (1 if x2 > x1 else -1) if abs(x2 - x1) > _EPS else 0,
        (1 if y2 > y1 else -1) if abs(y2 - y1) > _EPS else 0,
    )


def _vertices(segments: list[_Segment]) -> list[tuple[float, float]]:
    """Shared points of a polyline: the turns, plus the two endpoints."""
    points: list[tuple[float, float]] = []
    for x1, y1, x2, y2 in segments:
        points.append((x1, y1))
        points.append((x2, y2))
    return points


def _turns(segments: list[_Segment]) -> list[tuple[float, float]]:
    """Interior corners only -- a turn at either end is not a corner."""
    if len(segments) < 2:
        return []
    return [(x2, y2) for _, _, x2, y2 in segments[:-1]]


def _departure(segments: list[_Segment], pin: tuple[float, float]) -> tuple[int, int] | None:
    """Direction the wire travels in as it leaves ``pin``.

    The returned list from ``_route_avoiding_obstacles`` is *not* a traversal
    order: ``_deduplicate_segments`` regroups it horizontal-first and normalises
    every segment so its lower coordinate comes first.  So the departure is
    found by looking for the segment incident to the pin, never by index.
    """
    for x1, y1, x2, y2 in segments:
        if abs(x1 - pin[0]) <= _EPS and abs(y1 - pin[1]) <= _EPS:
            return _direction((x1, y1, x2, y2))
        if abs(x2 - pin[0]) <= _EPS and abs(y2 - pin[1]) <= _EPS:
            return _direction((x2, y2, x1, y1))
    return None


def _count_free_ends(segments: list[_Segment]) -> list[tuple[float, float]]:
    """Endpoints that no other segment shares.

    A connected run of segments is a chain: every interior vertex is used twice
    and exactly two ends are used once.  Counting odd-degree endpoints is the
    cheapest way to say "this is one wire" -- and it catches the failure mode
    where a stitched escape stub and the routed run never actually meet, which
    produces a polyline that looks like a route and is electrically open.
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


def _arrival(segments: list[_Segment], pin: tuple[float, float]) -> tuple[int, int] | None:
    """Direction the wire travels in as it reaches ``pin``."""
    departure = _departure(segments, pin)
    return None if departure is None else (-departure[0], -departure[1])


def _on_segment(point: tuple[float, float], segment: _Segment) -> bool:
    x1, y1, x2, y2 = segment
    px, py = point
    if abs(x1 - x2) <= _EPS:
        return abs(px - x1) <= _EPS and min(y1, y2) - _EPS <= py <= max(y1, y2) + _EPS
    if abs(y1 - y2) <= _EPS:
        return abs(py - y1) <= _EPS and min(x1, x2) - _EPS <= px <= max(x1, x2) + _EPS
    return False


def _collinear_overlap(one: _Segment, other: _Segment) -> bool:
    x1, y1, x2, y2 = one
    u1, v1, u2, v2 = other
    if abs(x1 - x2) <= _EPS and abs(u1 - u2) <= _EPS and abs(x1 - u1) <= _EPS:
        lo = max(min(y1, y2), min(v1, v2))
        hi = min(max(y1, y2), max(v1, v2))
        return hi - lo > _EPS
    if abs(y1 - y2) <= _EPS and abs(v1 - v2) <= _EPS and abs(y1 - v1) <= _EPS:
        lo = max(min(x1, x2), min(u1, u2))
        hi = min(max(x1, x2), max(u1, u2))
        return hi - lo > _EPS
    return False


def _perpendicular_crossing(one: _Segment, other: _Segment) -> bool:
    """One vertical against one horizontal, meeting strictly inside both."""
    x1, y1, x2, y2 = one
    u1, v1, u2, v2 = other
    if abs(x1 - x2) <= _EPS and abs(v1 - v2) <= _EPS:
        vertical, horizontal = one, other
    elif abs(y1 - y2) <= _EPS and abs(u1 - u2) <= _EPS:
        vertical, horizontal = other, one
    else:
        return False
    vx = vertical[0]
    hy = horizontal[1]
    return (
        min(horizontal[0], horizontal[2]) + _EPS < vx < max(horizontal[0], horizontal[2]) - _EPS
        and min(vertical[1], vertical[3]) + _EPS < hy < max(vertical[1], vertical[3]) - _EPS
    )


def _crossings(segments: list[_Segment], foreign: list[_Segment]) -> int:
    return sum(
        1 for segment in segments for other in foreign if _perpendicular_crossing(segment, other)
    )


def _length(segments: list[_Segment]) -> float:
    return sum(abs(x1 - x2) + abs(y1 - y2) for x1, y1, x2, y2 in segments)


# --------------------------------------------------------------------------
# Foreign geometry: cross it, never join it
# --------------------------------------------------------------------------


def test_route_never_overlaps_a_foreign_wire_collinearly() -> None:
    """Running along another net unions the two, so it is refused outright.

    The foreign wire lies exactly on the tempting straight line.  Overlap is the
    worst of the three foreign-geometry contacts because it is invisible in a
    render: the wires look like one wire because they are one wire.
    """
    foreign = [(0.0, 0.0, 10.0, 0.0)]
    segments = _route((0.0, 0.0), (10.0, 0.0), occupied=foreign)

    assert not any(_collinear_overlap(s, f) for s in segments for f in foreign), (
        f"route ran along a foreign wire: {segments}"
    )


def test_route_never_turns_on_a_foreign_wire() -> None:
    """A turn landing on a foreign wire drops a T-junction, which unions.

    ``occupied`` is deliberately not solid here: a crossing has to stay legal or
    a non-planar sheet cannot be routed at all.  What must not happen is a
    *vertex* of our route sitting on their wire.
    """
    foreign = [(0.0, 5.0, 10.0, 5.0)]
    segments = _route((0.0, 0.0), (10.0, 10.0), occupied=foreign)

    for turn in _turns(segments):
        assert not any(_on_segment(turn, f) for f in foreign), (
            f"route turned on a foreign wire at {turn}: {segments}"
        )


def test_route_never_lands_an_endpoint_on_a_foreign_wire() -> None:
    """An endpoint on a foreign wire unions even when it is not a turn."""
    foreign = [(0.0, 5.0, 10.0, 5.0)]
    segments = _route((0.0, 0.0), (10.0, 10.0), occupied=foreign)
    foreign_ends = {(0.0, 5.0), (10.0, 5.0)}

    for point in _vertices(segments):
        if point in {(0.0, 0.0), (10.0, 10.0)}:
            continue
        assert not any(_on_segment(point, f) for f in foreign), (
            f"route endpoint landed on a foreign wire at {point}: {segments}"
        )
    assert not {_vertices(segments)[0], _vertices(segments)[-1]} & foreign_ends


# --------------------------------------------------------------------------
# Crossing policy
#
# One shared set of fixtures, imported by the figure generator.  The crossing
# panel used to be drawn from a *different* wall than the test asserted on, so
# the picture showed a detour while the test checked a crossing -- a figure that
# disagrees with its test is worse than no figure.  Importing the fixtures makes
# that impossible.
#
# A wall is only a wall if it blocks BOTH ways round.  An earlier "detour" test
# used a wall spanning y=2..20 while the whole route sat at y=0: nothing was ever
# crossed, "0 crossings" was true for free, and the test proved nothing.
# --------------------------------------------------------------------------

#: Far too tall and deep to go round: the route has to cross it.
FIXTURE_FORCED_CROSSING = {
    "start": (0.0, 0.0),
    "end": (8.0, 0.0),
    "foreign": [(4.0, -8.0, 4.0, 20.0)],
}
#: Stops one grid short of the route, so slipping underneath is cheap.
FIXTURE_CHEAP_DETOUR = {
    "start": (0.0, 0.0),
    "end": (8.0, 0.0),
    "foreign": [(4.0, -1.0, 4.0, 20.0)],
}
#: A diagonal target behind a wall: one crossing, and no way to remove it.
FIXTURE_TOLL = {
    "start": (0.0, 0.0),
    "end": (8.0, 8.0),
    "foreign": [(4.0, -6.0, 4.0, 20.0)],
}
#: A wire the route can either cross or go round, with the round trip costing
#: less than one toll.  The only fixture here whose route genuinely changes with
#: the toll, which makes it the only one that can prove the toll is charged.
FIXTURE_TOLL_SENSITIVE = {
    "start": (2.0, 1.0),
    "end": (-2.0, -2.0),
    "foreign": [(-6.0, 0.0, 6.0, 0.0)],
}


def test_route_crosses_a_foreign_wire_perpendicularly_when_it_must() -> None:
    """A wall of foreign wire is crossed, not treated as impassable.

    The reference sheet is not planar.  A router that refuses crossings cannot
    connect it at all, so the rule is "cross, but pay".
    """
    foreign = FIXTURE_FORCED_CROSSING["foreign"]
    segments = _route(
        FIXTURE_FORCED_CROSSING["start"],
        FIXTURE_FORCED_CROSSING["end"],
        occupied=foreign,
    )

    assert _crossings(segments, foreign) == 1
    for segment in segments:
        for other in foreign:
            if _perpendicular_crossing(segment, other):
                assert abs(segment[1] - segment[3]) <= _EPS, (
                    "crossed by running along the wire rather than across it"
                )


def test_route_prefers_a_detour_over_a_crossing_when_it_is_cheap() -> None:
    """``CROSSING_PENALTY`` buys a detour, so a short one must be taken."""
    foreign = FIXTURE_CHEAP_DETOUR["foreign"]
    start, end = FIXTURE_CHEAP_DETOUR["start"], FIXTURE_CHEAP_DETOUR["end"]
    segments = _route(start, end, occupied=foreign)
    direct = abs(start[0] - end[0]) + abs(start[1] - end[1])

    assert _crossings(segments, foreign) == 0, (
        f"crossed for no reason; a detour under the wall was available: {segments}"
    )
    # Without this the assertion above is free: a route that never goes near the
    # wall also crosses it zero times.
    assert _length(segments) > direct, (
        f"no detour happened -- the route is the straight line: {segments}"
    )
    assert _length(segments) - direct < CROSSING_PENALTY


def test_crossing_toll_is_paid_rather_than_dodged_with_extra_corners() -> None:
    """A crossing is paid once, not dodged by buying corners.

    Charging the toll only on straight moves left a crossing made on a *turning*
    move free, and the search then bought two extra bends to dodge a toll it
    still had to pay -- same length, more corners.

    Scope, stated plainly: this fixture forces one crossing behind a wall it
    cannot go round, and checks that the route stays at three segments.  It does
    **not** isolate "the crossing lands on a turning move", and two verified
    reasons say such a fixture cannot exist on a uniform grid:

    1. ``_crossings_at`` is *node*-based -- it fires only when a grid node lies on
       the foreign wire.  A wire between two nodes (x=2.5 on a 1.0 grid) is
       invisible to the charge at any penalty, so a crossing strictly inside a
       step is never priced; that is the position a "crossing inside a turning
       step" needs.
    2. For a node-based crossing to coincide with a turn, the route must turn one
       node off the wire and step onto it, because turning *on* the wire is
       refused outright by ``_occupied_kind == 1``.  The search has no reason to
       prefer that shape, so it is not reachable as a cheapest route.

    What the old ``if not turning`` guard therefore cost is captured by
    ``test_raising_the_toll_changes_which_route_is_chosen`` above, plus the
    campaign on the reference sheet (D2 went 4 segments / 3 bends -> 2 / 1).
    """
    foreign = FIXTURE_TOLL["foreign"]
    segments = _route(FIXTURE_TOLL["start"], FIXTURE_TOLL["end"], occupied=foreign)

    # The wall has to actually be crossed, or "few corners" is satisfied by a
    # route that ignores it -- which is exactly how this test was vacuous.
    assert _crossings(segments, foreign) == 1, (
        f"fixture does not cross the wall, so it proves nothing: {segments}"
    )
    assert len(segments) <= 3, f"bought extra corners instead of paying the toll once: {segments}"


def test_raising_the_toll_changes_which_route_is_chosen() -> None:
    """The toll has to be load-bearing, not merely present.

    The other crossing tests check a route that cannot avoid a crossing, so they
    would pass even if the toll were ignored entirely.  This fixture is the one
    where the search has a real choice -- cross a short wire, or spend a few more
    grid steps going round its end -- and it then has to take both branches:

    * at the real toll the detour is cheaper, so no crossing;
    * with the toll set to zero the crossing is cheaper, so it is taken.

    The two branches are what proves the charge reaches the search.
    """
    start, end = FIXTURE_TOLL_SENSITIVE["start"], FIXTURE_TOLL_SENSITIVE["end"]
    foreign = FIXTURE_TOLL_SENSITIVE["foreign"]

    charged = _route(start, end, occupied=foreign)
    free = _route(start, end, occupied=foreign, crossing_penalty=0.0)

    assert _crossings(charged, foreign) == 0, f"paid a toll it could avoid: {charged}"
    assert _crossings(free, foreign) == 1, (
        f"toll is not reaching the search -- with it set to zero the route still "
        f"avoided the crossing: {free}"
    )
    assert _length(charged) > _length(free)


# --------------------------------------------------------------------------
# Bundle pitch
# --------------------------------------------------------------------------


def test_route_refuses_to_run_one_grid_from_a_parallel_wire() -> None:
    """1 grid apart is unreadable and the reference sheet never draws it.

    Measured on the reference sheet: of the wires with a parallel neighbour, 41
    sit at 2 grid and none at 1.  One step reads as one thick wire with a seam.
    """
    foreign = [(0.0, 5.0, 40.0, 5.0)]
    segments = _route((0.0, 0.0), (10.0, 0.0), occupied=foreign, max_bends=12)

    # Every run parallel to the foreign wire must sit at 2 grid or further.  A
    # run at exactly 1 grid is the failure this guards; 0 is collinear overlap,
    # which the overlap rule refuses separately.
    parallel_offsets = {
        round(abs(segment[1] - 5.0), 3)
        for segment in segments
        if abs(segment[1] - segment[3]) <= _EPS and abs(segment[1] - 5.0) > _EPS
    } | {
        round(abs(segment[0] - 5.0), 3)
        for segment in segments
        if abs(segment[0] - segment[2]) <= _EPS and abs(segment[0] - 5.0) > _EPS
    }

    assert parallel_offsets, f"fixture has no parallel run to judge: {segments}"
    assert min(parallel_offsets) > 1.0 + _EPS, (
        f"route ran {min(parallel_offsets)} grid from a foreign wire: {segments}"
    )


def test_route_bundles_at_two_grid_from_a_parallel_wire() -> None:
    """2 grid is the pitch, and the search pays to reach it.

    The target sits far from the foreign wire while the 2-grid lane is a detour.
    A router with no bundle reward stays on the straight line.
    """
    foreign = [(0.0, 2.0, 40.0, 2.0)]
    segments = _route((0.0, 0.0), (12.0, 0.0), occupied=foreign, max_bends=12)
    offsets = {round(abs(y1 - 2.0), 3) for x1, y1, x2, y2 in segments if abs(y1 - y2) <= _EPS}

    assert 2.0 in offsets or min(offsets) > 2.0 + _EPS, (
        f"route neither bundled at the pitch nor kept clear of it: {sorted(offsets)}"
    )


# --------------------------------------------------------------------------
# Module boundaries
# --------------------------------------------------------------------------


_SHEET = RouterBBox(4.0, 0.0, 20.0, 12.0)


def test_parallel_run_keeps_two_grid_from_a_module_boundary() -> None:
    """A drawn boundary is not crowded: 2 grid of clearance for parallel runs."""
    edges = module_boundary_edges([(4.0, 0.0, 20.0, 12.0)])

    assert hugs_boundary((5.0, 1.0, 5.0, 11.0), edges, 2.0), "1 grid must be refused"
    assert hugs_boundary((4.0, 1.0, 4.0, 11.0), edges, 2.0), "on the edge must be refused"
    assert not hugs_boundary((6.0, 1.0, 6.0, 11.0), edges, 2.0), "2 grid is the floor"
    assert not hugs_boundary((7.0, 1.0, 7.0, 11.0), edges, 2.0)


def test_crossing_a_module_boundary_perpendicularly_is_allowed() -> None:
    """A pin inside the box has to be reachable, so crossings stay legal."""
    edges = module_boundary_edges([(4.0, 0.0, 20.0, 12.0)])

    assert not hugs_boundary((0.0, 6.0, 30.0, 6.0), edges, 2.0), (
        "a wire crossing the boundary was refused"
    )


def test_crowding_needs_a_shared_span_not_merely_proximity() -> None:
    """Only a run *alongside* an edge crowds it; being near the corner does not.

    The rule pairs a run with edges of its own orientation and then asks whether
    the two spans overlap.  Both halves of that matter, so both are asserted --
    otherwise the test is a one-sided "close to a block is fine" claim, which is
    false: the vertical run below is free only because it shares no span, and a
    run that does share one at the same distance is refused.
    """
    edges = module_boundary_edges([(4.0, 0.0, 20.0, 12.0)])

    # 1 grid from the left edge's line, but the run lies wholly BEYOND that
    # edge's extent, so the two spans do not overlap: not crowding it, and it is
    # perpendicular to the top edge rather than alongside it.
    assert not hugs_boundary((5.0, 13.0, 5.0, 16.0), edges, 2.0)

    # Same starting point, same 1-grid offset, but now running ALONGSIDE the
    # top edge with a shared span -- refused.
    assert hugs_boundary((5.0, 13.0, 15.0, 13.0), edges, 2.0)

    # And a vertical run that does overlap the left edge's span -- refused.
    assert hugs_boundary((5.0, 5.0, 5.0, 10.0), edges, 2.0)


def test_route_to_a_pin_inside_a_module_box_gets_in() -> None:
    """The rule must not wall off the block it is protecting."""
    segments = _route((0.0, 6.0), (10.0, 6.0), boundaries=[_SHEET])

    assert any(abs(x2 - 10.0) <= _EPS and abs(y2 - 6.0) <= _EPS for _, _, x2, y2 in segments)
    assert not any(
        hugs_boundary(s, module_boundary_edges([(4.0, 0.0, 20.0, 12.0)]), 2.0) for s in segments
    ), f"reached the interior by crowding the boundary: {segments}"


# --------------------------------------------------------------------------
# Sheet pins
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rotation", "expected"),
    [(0, (1.0, 0.0)), (90, (0.0, -1.0)), (180, (-1.0, 0.0)), (270, (0.0, 1.0))],
)
def test_sheet_pin_escape_direction_follows_its_rotation(
    rotation: int, expected: tuple[float, float]
) -> None:
    """A sheet pin's rotation already says which way a wire must leave it.

    Without this the escape direction had to be guessed from the nearest edge of
    the pin's box, and a pin sitting on that box's outline gives distance 0 to
    its own edge -- no usable signal at all.
    """
    assert outward_normal_for_rotation(rotation) == expected


# --------------------------------------------------------------------------
# Leaving and arriving at a pin
# --------------------------------------------------------------------------


#: A pin sits *on* its own keepout outline, exactly as a real symbol pin does.
#: The keepout is not decoration in these two tests: it is what makes the router
#: emit an escape stub, and the escape stub is what honours the normal.
#: Coordinates are exact multiples of 1.27 mm.  That is not tidiness: the router
#: quantises every node with ``round(point/grid_mm)``, so an off-grid pin makes
#: the stitched escape stub and the routed run miss each other entirely -- see
#: ``test_route_is_connected_for_a_pin_off_the_router_grid``, which pins that
#: defect down separately.
_START_PIN = (10.16, 12.7)
_START_PIN_BOX = BBox(10.16, 10.16, 13.97, 16.51)
_END_PIN = (20.32, 5.08)
_END_PIN_BOX = BBox(20.32, 2.54, 24.13, 6.35)


def test_route_leaves_along_the_pin_normal() -> None:
    """A wire leaves a pin travelling outwards, never across the grain.

    The target is due south of a pin that faces west, so the shortest wire turns
    on the pin.  The router instead runs out along the normal first and turns
    away from the pin: the escape stub is emitted before the search starts, so
    the search never gets to choose the first move.

    Without the owning keepout there is no escape stub at all and this guarantee
    does not hold -- see ``test_escape_stub_needs_an_owning_keepout``.  These
    tests use the raw router deliberately: it is the layer that used to ignore
    pin orientation, and seeding it with ``start_dir`` was the fix being guarded.
    """
    segments, warning = _route_avoiding_obstacles(
        _START_PIN,
        (12.7, 3.81),
        [_START_PIN_BOX],
        False,
        None,
        (-1.0, 0.0),
        None,
    )

    assert warning is None
    _assert_single_chain(segments)
    assert _departure(segments, _START_PIN) == (-1, 0), f"left the pin across the grain: {segments}"


def test_route_arrives_against_the_target_pin_normal() -> None:
    """The final move travels back into the pin, so the last stub is straight.

    ``end_normal`` is the pin's *outward* direction, so the wire has to arrive
    travelling the opposite way -- here the pin faces west and the wire must
    come in eastwards.
    """
    segments, warning = _route_avoiding_obstacles(
        (5.08, 12.7),
        _END_PIN,
        [_END_PIN_BOX],
        False,
        None,
        None,
        (-1.0, 0.0),
    )

    assert warning is None
    _assert_single_chain(segments)
    assert _arrival(segments, _END_PIN) == (1, 0), (
        f"arrived on {_arrival(segments, _END_PIN)}, so the last stub bends at the pin"
    )


def test_route_is_connected_for_a_pin_off_the_router_grid() -> None:
    """An off-grid pin must still yield one connected Manhattan run.

    ``_escape_point`` works in millimetres and lands between nodes; the router
    quantises every node with ``round(point / grid_mm)``.  The stub used to be
    stitched to the raw landing, leaving it 0.70 mm short of the run: four free
    ends, an open wire that renders exactly like a route.  The landing is now
    snapped onto the lattice and the offset taken out as a perpendicular step.

    KiCad pins usually sit on the 1.27 mm grid, so this never showed up on the
    reference board -- that was luck of the standard, not a guarantee in the
    code, and it stopped being luck the moment a pin sat off-grid.
    """
    segments, warning = _route_avoiding_obstacles(
        (10.0, 12.0),
        (12.0, 4.0),
        [BBox(10.0, 10.0, 14.0, 14.0)],
        False,
        None,
        (-1.0, 0.0),
        None,
    )

    assert warning is None
    _assert_single_chain(segments)
    assert not [s for s in segments if abs(s[0] - s[2]) > 1e-6 and abs(s[1] - s[3]) > 1e-6], (
        f"diagonal segment in a Manhattan run: {segments}"
    )


def test_escape_stub_needs_an_owning_keepout() -> None:
    """The normal is honoured by the escape stub, so it needs an owning box.

    Stated plainly rather than left as a silent difference between two kinds of
    endpoint: a pin with no owning keepout -- a bare coordinate, or a power
    symbol placed in open space -- gets no stub, and the search is then free to
    depart across the grain.  Coordinates are exact grid multiples so a snap
    cannot move the pin out from under the assertion.
    """
    pin, target = (10.16, 12.7), (10.16, 3.81)

    owned, _ = _route_avoiding_obstacles(
        pin, target, [BBox(10.16, 12.7, 13.97, 16.51)], False, None, (1.0, 0.0), None
    )
    unowned, _ = _route_avoiding_obstacles(pin, target, [], False, None, (1.0, 0.0), None)

    assert _departure(owned, pin) == (1, 0)
    assert _departure(unowned, pin) == (0, -1), (
        "expected the un-stubbed case to fall through to the bare search"
    )


def test_direct_shortcut_is_refused_when_it_turns_at_a_pin() -> None:
    """The two-segment shortcut yields to A* when it would hinge on a pin.

    This one *is* enforced: the direct run is inspected before it is returned, so
    unlike the priced hinge above it cannot slip through.  ``segments[0]`` is the
    departure because a direct run is still in traversal order.
    """
    from kicad_mcp.tools.schematic import _manhattan_segments, _route_avoids_pin_hinge

    x_first = _manhattan_segments((10.0, 10.0), (0.0, 0.0), False)
    assert _direction(x_first[0]) == (-1, 0)
    # The pin faces up, so running left first hinges on it and must be refused.
    assert _route_avoids_pin_hinge(x_first, (0.0, -1.0), None)

    y_first = _manhattan_segments((0.0, 0.0), (10.0, 10.0), False)
    assert not _route_avoids_pin_hinge(y_first, (0.0, -1.0), None) or _direction(y_first[0]) != (
        0,
        -1,
    )
