"""Grid-based A* router for KiCad schematic wire segments."""

from __future__ import annotations

import heapq
from dataclasses import dataclass

Point = tuple[float, float]
Segment = tuple[float, float, float, float]

#: Coordinate tolerance in millimetres for coincidence tests.
_EPS = 1e-6

#: Price of one crossing, in grid steps.  A move costs 1.0 and a bend costs 3.0,
#: so 20 puts a crossing at roughly 20 grid steps (25.4 mm on the 1.27 mm
#: schematic grid): worth routing around, not worth an absurd detour.
#: Crossings stay *legal* -- a router that refuses them cannot connect a
#: non-planar sheet at all -- they are merely expensive.
CROSSING_PENALTY = 20.0


def point_on_segment(point: Point, segment: Segment, *, tolerance: float = _EPS) -> bool:
    """True when an orthogonal run passes through ``point``, ends included."""
    px, py = point
    x1, y1, x2, y2 = segment
    if abs(y1 - y2) <= tolerance:
        return (
            abs(py - y1) <= tolerance and min(x1, x2) - tolerance <= px <= max(x1, x2) + tolerance
        )
    if abs(x1 - x2) <= tolerance:
        return (
            abs(px - x1) <= tolerance and min(y1, y2) - tolerance <= py <= max(y1, y2) + tolerance
        )
    return False


def _at_endpoint(point: Point, segment: Segment, *, tolerance: float = _EPS) -> bool:
    """True when ``point`` coincides with either end of ``segment``."""
    px, py = point
    return (abs(px - segment[0]) <= tolerance and abs(py - segment[1]) <= tolerance) or (
        abs(px - segment[2]) <= tolerance and abs(py - segment[3]) <= tolerance
    )


def _inside_segment(point: Point, segment: Segment, *, tolerance: float = _EPS) -> bool:
    """True when ``point`` lies strictly inside an orthogonal run.

    Endpoints are excluded on purpose: standing on a foreign wire's end is
    already refused outright, so a node this accepts is one the path goes
    *through*, which is exactly one crossing.
    """
    return point_on_segment(point, segment, tolerance=tolerance) and not _at_endpoint(
        point, segment, tolerance=tolerance
    )


def _collinear_overlap(one: Segment, other: Segment, *, tolerance: float = _EPS) -> bool:
    """True when two aligned runs share length, touching ends included.

    KiCad unions wires that overlap or meet end-to-end, so both count as a
    merge.  A bare perpendicular crossing shares a single point and stays two
    nets, which is why the runner-up case returns ``False``.
    """
    if abs(one[1] - one[3]) <= tolerance and abs(other[1] - other[3]) <= tolerance:
        if abs(one[1] - other[1]) > tolerance:
            return False
        return (
            max(min(one[0], one[2]), min(other[0], other[2]))
            <= min(max(one[0], one[2]), max(other[0], other[2])) + tolerance
        )
    if abs(one[0] - one[2]) <= tolerance and abs(other[0] - other[2]) <= tolerance:
        if abs(one[0] - other[0]) > tolerance:
            return False
        return (
            max(min(one[1], one[3]), min(other[1], other[3]))
            <= min(max(one[1], one[3]), max(other[1], other[3])) + tolerance
        )
    return False


def segments_merge(one: Segment, other: Segment, *, tolerance: float = _EPS) -> bool:
    """True when KiCad's union-by-geometry rules would join two wire runs.

    Wires union when they overlap along a shared axis or when either one's
    endpoint lands anywhere on the other.  A bare perpendicular crossing does
    neither, which is why a router may pass over another net.
    """
    if _collinear_overlap(one, other, tolerance=tolerance):
        return True
    for point in ((one[0], one[1]), (one[2], one[3])):
        if point_on_segment(point, other, tolerance=tolerance):
            return True
    for point in ((other[0], other[1]), (other[2], other[3])):
        if point_on_segment(point, one, tolerance=tolerance):
            return True
    return False


def perpendicular_crossing(one: Segment, other: Segment, *, tolerance: float = _EPS) -> bool:
    """True when two orthogonal runs cross at a point interior to both.

    This is the measurement counterpart to the router's occupancy rules: it
    reports the crossings KiCad leaves unconnected, on the finished segments
    (escape stubs included), where the search only needed to price them.  A
    merge is never also a crossing, hence the guard.
    """
    if segments_merge(one, other, tolerance=tolerance):
        return False
    x1, y1, x2, y2 = one
    u1, v1, u2, v2 = other
    if abs(y1 - y2) <= tolerance and abs(u1 - u2) <= tolerance:
        return (
            min(x1, x2) + tolerance < u1 < max(x1, x2) - tolerance
            and min(v1, v2) + tolerance < y1 < max(v1, v2) - tolerance
        )
    if abs(x1 - x2) <= tolerance and abs(v1 - v2) <= tolerance:
        return (
            min(y1, y2) + tolerance < v1 < max(y1, y2) - tolerance
            and min(u1, u2) + tolerance < x1 < max(u1, u2) - tolerance
        )
    return False


@dataclass(frozen=True)
class RouterBBox:
    """Axis-aligned obstacle bounds in millimetres."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float

    def contains(self, point: Point) -> bool:
        x_mm, y_mm = point
        return self.x_min <= x_mm <= self.x_max and self.y_min <= y_mm <= self.y_max


class SchematicRouter:
    """A* schematic router with Manhattan movement and bend penalties."""

    def __init__(
        self,
        grid_mm: float = 2.54,
        obstacles: list[RouterBBox] | None = None,
        max_steps: int = 20000,
        occupied: list[Segment] | None = None,
        crossing_penalty: float = CROSSING_PENALTY,
    ) -> None:
        self.grid_mm = grid_mm
        self.obstacles = list(obstacles or [])
        self.max_steps = max_steps
        #: Wire geometry owned by *other* nets.  Unlike ``obstacles`` these are
        #: not solid: a route may cross one perpendicularly, because KiCad only
        #: unions a crossing when an endpoint lands on the other wire.  What it
        #: may not do is run along one, or turn on one.
        self.occupied = list(occupied or [])
        self.crossing_penalty = crossing_penalty
        self._kind_cache: dict[tuple[int, int], int] = {}
        self._crossing_cache: dict[tuple[int, int], int] = {}

    def _grid(self, point: Point) -> tuple[int, int]:
        return (round(point[0] / self.grid_mm), round(point[1] / self.grid_mm))

    def _point(self, node: tuple[int, int]) -> Point:
        return (node[0] * self.grid_mm, node[1] * self.grid_mm)

    def _blocked(self, node: tuple[int, int], start: tuple[int, int], end: tuple[int, int]) -> bool:
        if node in {start, end}:
            return False
        point = self._point(node)
        return any(obstacle.contains(point) for obstacle in self.obstacles)

    def _occupied_kind(self, node: tuple[int, int]) -> int:
        """How foreign wire geometry covers a grid node.

        ``0`` free, ``1`` inside a foreign run (a through-move is fine, a turn
        there would drop a T-junction), ``2`` on a foreign run's endpoint (not
        standable at all -- a wire ending on ours unions the two nets even when
        we pass straight through).
        """
        if not self.occupied:
            return 0
        cached = self._kind_cache.get(node)
        if cached is not None:
            return cached
        point = self._point(node)
        kind = 0
        for segment in self.occupied:
            if not point_on_segment(point, segment):
                continue
            if _at_endpoint(point, segment):
                kind = 2
                break
            kind = 1
        self._kind_cache[node] = kind
        return kind

    def _edge_overlaps_occupied(self, current: tuple[int, int], nxt: tuple[int, int]) -> bool:
        """True when a one-step move would run along a foreign wire."""
        if not self.occupied:
            return False
        here = self._point(current)
        there = self._point(nxt)
        edge = (here[0], here[1], there[0], there[1])
        return any(_collinear_overlap(edge, segment) for segment in self.occupied)

    def _crossings_at(self, node: tuple[int, int]) -> int:
        """How many foreign runs this node sits inside.

        A count rather than a flag, because two nets may cross the same point.
        Only reached for straight through-moves, so every run counted here is
        genuinely crossed rather than run along.
        """
        if not self.occupied:
            return 0
        cached = self._crossing_cache.get(node)
        if cached is None:
            point = self._point(node)
            cached = sum(1 for segment in self.occupied if _inside_segment(point, segment))
            self._crossing_cache[node] = cached
        return cached

    @staticmethod
    def _heuristic(node: tuple[int, int], end: tuple[int, int]) -> float:
        return abs(node[0] - end[0]) + abs(node[1] - end[1])

    def route(self, start: Point, end: Point, max_bends: int = 4) -> list[Segment] | None:
        """Return routed Manhattan segments, or None if no bounded route is found.

        With ``occupied`` set the search also refuses to merge with another
        net: it will not run along a foreign wire (collinear overlap) and will
        not place a vertex or an endpoint on one.  Perpendicular crossings stay
        legal, matching KiCad's union-by-geometry rules, but each one is charged
        ``crossing_penalty`` so the search prefers a longer crossing-free route
        when one is cheap enough.  ``crossing_penalty=0`` restores the old
        shortest-path behaviour.
        """
        start_node = self._grid(start)
        end_node = self._grid(end)
        # The two endpoints are pins of the net being routed.  Foreign geometry
        # sitting on them is a pre-existing condition, not this route's doing.
        exempt = {start_node, end_node}
        self._kind_cache = {}
        self._crossing_cache = {}
        queue: list[tuple[float, int, tuple[int, int], tuple[int, int] | None, int]] = []
        heapq.heappush(queue, (0.0, 0, start_node, None, 0))
        came_from: dict[tuple[int, int], tuple[int, int] | None] = {start_node: None}
        best_cost: dict[tuple[int, int], float] = {start_node: 0.0}
        directions = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        explored = 0

        while queue and explored < self.max_steps:
            _, bends, current, previous_dir, _tie = heapq.heappop(queue)
            explored += 1
            if current == end_node:
                return self._segments_from_path(self._reconstruct(came_from, current))

            for direction in directions:
                nxt = (current[0] + direction[0], current[1] + direction[1])
                if self._blocked(nxt, start_node, end_node):
                    continue
                turning = previous_dir is not None and previous_dir != direction
                # A turn makes ``current`` a vertex of the path.  A vertex on a
                # foreign wire is an endpoint-on-wire contact, which KiCad unions.
                if turning and current not in exempt and self._occupied_kind(current) == 1:
                    continue
                # A foreign wire's own endpoint must never be stood on, even in
                # a straight through-move: that endpoint would lie on our run.
                if nxt not in exempt and self._occupied_kind(nxt) == 2:
                    continue
                if self._edge_overlaps_occupied(current, nxt):
                    continue
                next_bends = bends + (1 if turning else 0)
                if next_bends > max_bends:
                    continue
                move_cost = 1.0 + (3.0 if turning else 0.0)
                if not turning:
                    # Every node reaching this line is a pass-through: a turn on
                    # a foreign wire was refused above and a parallel foreign run
                    # was refused as collinear overlap.  So a node inside one is
                    # exactly one crossing, priced rather than forbidden.
                    move_cost += self.crossing_penalty * self._crossings_at(nxt)
                new_cost = best_cost[current] + move_cost
                if new_cost >= best_cost.get(nxt, float("inf")):
                    continue
                came_from[nxt] = current
                best_cost[nxt] = new_cost
                priority = new_cost + self._heuristic(nxt, end_node)
                heapq.heappush(queue, (priority, next_bends, nxt, direction, explored))
        return None

    @staticmethod
    def _reconstruct(
        came_from: dict[tuple[int, int], tuple[int, int] | None],
        current: tuple[int, int],
    ) -> list[tuple[int, int]]:
        path = [current]
        previous = came_from[current]
        while previous is not None:
            current = previous
            path.append(current)
            previous = came_from[current]
        path.reverse()
        return path

    def _segments_from_path(self, path: list[tuple[int, int]]) -> list[Segment]:
        if len(path) < 2:
            return []
        points = [self._point(node) for node in path]
        segments: list[Segment] = []
        start = points[0]
        previous = points[0]
        direction = (
            int(points[1][0] - points[0][0]),
            int(points[1][1] - points[0][1]),
        )
        for point in points[1:]:
            next_direction = (
                int(point[0] - previous[0]),
                int(point[1] - previous[1]),
            )
            if next_direction != direction:
                segments.append((start[0], start[1], previous[0], previous[1]))
                start = previous
                direction = next_direction
            previous = point
        segments.append((start[0], start[1], previous[0], previous[1]))
        return [segment for segment in segments if segment[:2] != segment[2:]]
