"""Regression tests for obstacle-aware schematic wire routing.

Three layers used to fail together, and each gets its own coverage here:

1. ``get_symbol_primitive_bounds`` -- exact symbol extents derived from library
   primitives.  A pin-only or hardcoded box either buries the pin it is meant to
   expose (the historical ``padded(5.0)`` trap) or clips real geometry such as
   capacitor plates, LED emission arrows and the BJT enclosing circle.

2. ``_route_avoiding_obstacles`` -- the escape-and-route strategy.  It steps one
   grid unit along the pin's outward normal so A* starts in free space instead
   of inside a padded symbol box, then routes between the escape points with
   every symbol box active as a hard keepout.

3. Inter-net awareness -- the router still has none.  Independently routed nets
   converge on the same lowest-cost channels and merge by geometry in KiCad,
   which is a silent short.  ``test_router_lacks_inter_net_awareness`` documents
   that gap as ``xfail(strict=True)``: fixing the router turns the test red and
   forces the marker to be removed rather than quietly forgotten.

Most tests run against hermetic fixture libraries written into ``tmp_path``, so
they exercise the real parsing and routing code on a bare CI runner with no
KiCad installation.  The handful that need the genuine ``Device``/``Timer``
libraries are marked ``requires_kicad_library`` and skip when they are absent.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from kicad_mcp.tools import schematic as schematic_module
from kicad_mcp.tools.schematic import (
    SCHEMATIC_GRID_MM,
    BBox,
    _get_symbol_bboxes,
    _route_avoiding_obstacles,
    _segment_intersects_bbox,
    _snap_point,
    _symbol_library_file,
    get_pin_positions,
    get_symbol_primitive_bounds,
)

_EPS = 1e-6
_MM = tuple[float, float]
_Segment = tuple[float, float, float, float]

#: Fixture library.  Each symbol mirrors the drawn geometry of a real KiCad
#: symbol closely enough to exercise every primitive branch of the extent
#: parser: a rectangle, plates, a circle, overhanging arrows and pin rows.
FIXTURE_LIBRARY = """(kicad_symbol_lib
\t(version 20231120)
\t(generator "kicad-mcp-pro-tests")
\t(symbol "R"
\t\t(pin_numbers (hide yes))
\t\t(pin_names (offset 0))
\t\t(exclude_from_sim no)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(property "Reference" "R" (at 2.032 0 90) (effects (font (size 1.27 1.27))))
\t\t(property "Value" "R" (at 0 0 90) (effects (font (size 1.27 1.27))))
\t\t(symbol "R_0_1"
\t\t\t(rectangle (start -1.016 -2.54) (end 1.016 2.54)
\t\t\t\t(stroke (width 0.254) (type default)) (fill (type none))
\t\t\t)
\t\t)
\t\t(symbol "R_1_1"
\t\t\t(pin passive line (at 0 3.81 270) (length 1.27)
\t\t\t\t(name "" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "1" (effects (font (size 1.27 1.27))))
\t\t\t)
\t\t\t(pin passive line (at 0 -3.81 90) (length 1.27)
\t\t\t\t(name "" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "2" (effects (font (size 1.27 1.27))))
\t\t\t)
\t\t)
\t)
\t(symbol "C"
\t\t(pin_numbers (hide yes))
\t\t(pin_names (offset 0.254))
\t\t(exclude_from_sim no)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(property "Reference" "C" (at 0.635 2.54 0) (effects (font (size 1.27 1.27))))
\t\t(property "Value" "C" (at 0.635 -2.54 0) (effects (font (size 1.27 1.27))))
\t\t(symbol "C_0_1"
\t\t\t(polyline (pts (xy -2.032 0.762) (xy 2.032 0.762))
\t\t\t\t(stroke (width 0.508) (type default)) (fill (type none))
\t\t\t)
\t\t\t(polyline (pts (xy -2.032 -0.762) (xy 2.032 -0.762))
\t\t\t\t(stroke (width 0.508) (type default)) (fill (type none))
\t\t\t)
\t\t)
\t\t(symbol "C_1_1"
\t\t\t(pin passive line (at 0 3.81 270) (length 2.794)
\t\t\t\t(name "" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "1" (effects (font (size 1.27 1.27))))
\t\t\t)
\t\t\t(pin passive line (at 0 -3.81 90) (length 2.794)
\t\t\t\t(name "" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "2" (effects (font (size 1.27 1.27))))
\t\t\t)
\t\t)
\t)
\t(symbol "Q_NPN"
\t\t(pin_numbers (hide yes))
\t\t(pin_names (offset 0) (hide yes))
\t\t(exclude_from_sim no)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(property "Reference" "Q" (at 5.08 1.27 0) (effects (font (size 1.27 1.27))))
\t\t(property "Value" "Q_NPN" (at 5.08 -1.27 0) (effects (font (size 1.27 1.27))))
\t\t(symbol "Q_NPN_0_1"
\t\t\t(polyline (pts (xy 0.635 1.905) (xy 0.635 -1.905))
\t\t\t\t(stroke (width 0.508) (type default)) (fill (type none))
\t\t\t)
\t\t\t(circle (center 1.27 0) (radius 2.8194)
\t\t\t\t(stroke (width 0.254) (type default)) (fill (type none))
\t\t\t)
\t\t)
\t\t(symbol "Q_NPN_1_1"
\t\t\t(pin input line (at -5.08 0 0) (length 2.54)
\t\t\t\t(name "B" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "B" (effects (font (size 1.27 1.27))))
\t\t\t)
\t\t\t(pin passive line (at 2.54 5.08 270) (length 2.54)
\t\t\t\t(name "C" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "C" (effects (font (size 1.27 1.27))))
\t\t\t)
\t\t\t(pin passive line (at 2.54 -5.08 90) (length 2.54)
\t\t\t\t(name "E" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "E" (effects (font (size 1.27 1.27))))
\t\t\t)
\t\t)
\t)
\t(symbol "LED"
\t\t(pin_numbers (hide yes))
\t\t(pin_names (offset 1.016) (hide yes))
\t\t(exclude_from_sim no)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(property "Reference" "D" (at 0 2.54 0) (effects (font (size 1.27 1.27))))
\t\t(property "Value" "LED" (at 0 -2.54 0) (effects (font (size 1.27 1.27))))
\t\t(symbol "LED_0_1"
\t\t\t(polyline (pts (xy -1.27 -1.27) (xy -1.27 1.27))
\t\t\t\t(stroke (width 0.254) (type default)) (fill (type none))
\t\t\t)
\t\t\t(polyline (pts (xy -1.27 0) (xy 1.27 -1.27) (xy 1.27 1.27) (xy -1.27 0))
\t\t\t\t(stroke (width 0.254) (type default)) (fill (type none))
\t\t\t)
\t\t\t(polyline (pts (xy -3.048 -0.762) (xy -4.572 -2.286))
\t\t\t\t(stroke (width 0) (type default)) (fill (type none))
\t\t\t)
\t\t\t(polyline (pts (xy -4.572 -2.286) (xy -3.81 -2.286) (xy -4.572 -1.524) (xy -4.572 -2.286))
\t\t\t\t(stroke (width 0) (type default)) (fill (type outline))
\t\t\t)
\t\t\t(polyline (pts (xy -1.778 -0.762) (xy -3.302 -2.286))
\t\t\t\t(stroke (width 0) (type default)) (fill (type none))
\t\t\t)
\t\t\t(polyline (pts (xy -3.302 -2.286) (xy -2.54 -2.286) (xy -3.302 -1.524) (xy -3.302 -2.286))
\t\t\t\t(stroke (width 0) (type default)) (fill (type outline))
\t\t\t)
\t\t)
\t\t(symbol "LED_1_1"
\t\t\t(pin passive line (at -3.81 0 0) (length 2.54)
\t\t\t\t(name "K" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "1" (effects (font (size 1.27 1.27))))
\t\t\t)
\t\t\t(pin passive line (at 3.81 0 180) (length 2.54)
\t\t\t\t(name "A" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "2" (effects (font (size 1.27 1.27))))
\t\t\t)
\t\t)
\t)
\t(symbol "IC8"
\t\t(pin_numbers (hide yes))
\t\t(pin_names (offset 1.016))
\t\t(exclude_from_sim no)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(property "Reference" "U" (at -10.16 11.43 0) (effects (font (size 1.27 1.27))))
\t\t(property "Value" "IC8" (at 10.16 11.43 0) (effects (font (size 1.27 1.27))))
\t\t(symbol "IC8_0_1"
\t\t\t(rectangle (start -10.16 10.16) (end 10.16 -10.16)
\t\t\t\t(stroke (width 0.254) (type default)) (fill (type background))
\t\t\t)
\t\t)
\t\t(symbol "IC8_1_1"
\t\t\t(pin power_in line (at -12.7 7.62 0) (length 2.54)
\t\t\t\t(name "VCC" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "8" (effects (font (size 1.27 1.27))))
\t\t\t)
\t\t\t(pin input line (at -12.7 2.54 0) (length 2.54)
\t\t\t\t(name "RST" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "4" (effects (font (size 1.27 1.27))))
\t\t\t)
\t\t\t(pin input line (at -12.7 -2.54 0) (length 2.54)
\t\t\t\t(name "TRIG" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "2" (effects (font (size 1.27 1.27))))
\t\t\t)
\t\t\t(pin power_in line (at -12.7 -7.62 0) (length 2.54)
\t\t\t\t(name "GND" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "1" (effects (font (size 1.27 1.27))))
\t\t\t)
\t\t\t(pin output line (at 12.7 -7.62 180) (length 2.54)
\t\t\t\t(name "OUT" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "3" (effects (font (size 1.27 1.27))))
\t\t\t)
\t\t\t(pin input line (at 12.7 -2.54 180) (length 2.54)
\t\t\t\t(name "CONT" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "5" (effects (font (size 1.27 1.27))))
\t\t\t)
\t\t\t(pin input line (at 12.7 2.54 180) (length 2.54)
\t\t\t\t(name "THRES" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "6" (effects (font (size 1.27 1.27))))
\t\t\t)
\t\t\t(pin input line (at 12.7 7.62 180) (length 2.54)
\t\t\t\t(name "DISCH" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "7" (effects (font (size 1.27 1.27))))
\t\t\t)
\t\t)
\t)
\t(symbol "CONN4"
\t\t(pin_numbers (hide yes))
\t\t(pin_names (offset 1.016))
\t\t(exclude_from_sim no)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(property "Reference" "J" (at 0 11.43 0) (effects (font (size 1.27 1.27))))
\t\t(property "Value" "CONN4" (at 0 -6.35 0) (effects (font (size 1.27 1.27))))
\t\t(symbol "CONN4_0_1"
\t\t\t(rectangle (start -1.27 6.35) (end 1.27 -3.81)
\t\t\t\t(stroke (width 0.254) (type default)) (fill (type background))
\t\t\t)
\t\t)
\t\t(symbol "CONN4_1_1"
\t\t\t(pin passive line (at -5.08 5.08 0) (length 3.81)
\t\t\t\t(name "Pin_1" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "1" (effects (font (size 1.27 1.27))))
\t\t\t)
\t\t\t(pin passive line (at -5.08 2.54 0) (length 3.81)
\t\t\t\t(name "Pin_2" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "2" (effects (font (size 1.27 1.27))))
\t\t\t)
\t\t\t(pin passive line (at -5.08 0 0) (length 3.81)
\t\t\t\t(name "Pin_3" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "3" (effects (font (size 1.27 1.27))))
\t\t\t)
\t\t\t(pin passive line (at -5.08 -2.54 0) (length 3.81)
\t\t\t\t(name "Pin_4" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "4" (effects (font (size 1.27 1.27))))
\t\t\t)
\t\t)
\t)	(symbol "FLAT"
		(pin_numbers (hide yes))
		(pin_names (offset 0))
		(exclude_from_sim no)
		(in_bom yes)
		(on_board yes)
		(property "Reference" "F" (at 0 2.54 0) (effects (font (size 1.27 1.27))))
		(property "Value" "FLAT" (at 0 -2.54 0) (effects (font (size 1.27 1.27))))
		(rectangle (start -1.27 -1.27) (end 1.27 1.27)
			(stroke (width 0.254) (type default)) (fill (type none))
		)
		(pin passive line (at -3.81 0 0) (length 2.54)
			(name "" (effects (font (size 1.27 1.27))))
			(number "1" (effects (font (size 1.27 1.27))))
		)
		(pin passive line (at 3.81 0 180) (length 2.54)
			(name "" (effects (font (size 1.27 1.27))))
			(number "2" (effects (font (size 1.27 1.27))))
		)
	)	(symbol "EMPTY"
		(pin_numbers (hide yes))
		(pin_names (offset 0))
		(exclude_from_sim no)
		(in_bom yes)
		(on_board yes)
		(property "Reference" "X" (at 0 2.54 0) (effects (font (size 1.27 1.27))))
		(property "Value" "EMPTY" (at 0 -2.54 0) (effects (font (size 1.27 1.27))))
	)
)
"""

#: ``(symbol, expected_width_mm, expected_height_mm)`` for the fixture library.
FIXTURE_EXTENTS: list[tuple[str, float, float]] = [
    ("R", 2.032, 7.62),
    ("C", 4.064, 7.62),
    ("Q_NPN", 9.1694, 10.16),
    ("LED", 8.382, 3.556),
    ("IC8", 25.4, 20.32),
    ("CONN4", 6.35, 10.16),
    # FLAT keeps its primitives inline with no ``_0_1``/``_1_1`` unit children,
    # as flattened and imported symbols often do.
    ("FLAT", 7.62, 2.54),
]

#: ``(reference, symbol, x_mm, y_mm)`` sheet used by the routing tests.  It keeps
#: the awkward shapes (overhanging LED, circular BJT, wide capacitor, crowded
#: 8-pin IC) that made routing fail in practice.
SHEET: list[tuple[str, str, float, float]] = [
    ("R1", "R", 40.64, 63.5),
    ("C1", "C", 81.28, 63.5),
    ("LED1", "LED", 121.92, 63.5),
    ("Q1", "Q_NPN", 162.56, 63.5),
    ("J1", "CONN4", 40.64, 139.7),
    ("U2", "IC8", 111.76, 139.7),
]


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def fixture_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point symbol resolution at a hermetic library written into ``tmp_path``.

    CI runs on a bare runner with no KiCad installation, so the tests must not
    depend on the system symbol libraries being present.
    """
    library_dir = tmp_path / "symbols"
    library_dir.mkdir()
    (library_dir / "Fixture.kicad_sym").write_text(FIXTURE_LIBRARY, encoding="utf-8")

    def _resolve(library: str) -> Path | None:
        candidate = library_dir / f"{library}.kicad_sym"
        return candidate if candidate.exists() else None

    monkeypatch.setattr(schematic_module, "_symbol_library_file", _resolve)
    return library_dir


@pytest.fixture
def boxes_by_ref(fixture_library: Path) -> dict[str, BBox]:
    """Exact keepout box for every component on the fixture sheet."""
    return {
        ref: BBox(*get_symbol_primitive_bounds("Fixture", sym, x, y, 0, 1))  # type: ignore[misc]
        for ref, sym, x, y in SHEET
    }


# --------------------------------------------------------------------------- #
# geometry helpers
# --------------------------------------------------------------------------- #
def _pin(ref: str, number: str) -> _MM:
    """Snapped coordinate of one pin on the fixture sheet."""
    for candidate, sym, x, y in SHEET:
        if candidate == ref:
            return _snap_point(*get_pin_positions("Fixture", sym, x, y, 0, 1)[number], True)
    raise AssertionError(f"unknown reference {ref}")


def _pins() -> list[dict[str, object]]:
    """Every pin on the fixture sheet, tagged with its owning reference."""
    pins: list[dict[str, object]] = []
    for ref, sym, x, y in SHEET:
        for number, (px, py) in get_pin_positions("Fixture", sym, x, y, 0, 1).items():
            pins.append({"ref": ref, "pin": number, "point": _snap_point(px, py, True)})
    return pins


def _penetrates(segment: _Segment, box: BBox) -> bool:
    """True if an orthogonal segment crosses the *interior* of ``box``."""
    x1, y1, x2, y2 = segment
    if abs(y1 - y2) <= _EPS:
        if box.y_min + _EPS < y1 < box.y_max - _EPS:
            return max(min(x1, x2), box.x_min) < min(max(x1, x2), box.x_max) - _EPS
        return False
    if abs(x1 - x2) <= _EPS:
        if box.x_min + _EPS < x1 < box.x_max - _EPS:
            return max(min(y1, y2), box.y_min) < min(max(y1, y2), box.y_max) - _EPS
        return False
    return False


def _foreign_crossings(
    segments: list[_Segment], boxes_by_ref: dict[str, BBox], owners: set[str]
) -> list[tuple[_Segment, str]]:
    """Segments that cut through a component other than the two being joined.

    A net's escape stub legitimately touches the keepout it is leaving, so the
    two owning symbols are excluded; every other symbol is a defect.
    """
    return [
        (segment, ref)
        for segment in segments
        for ref, box in boxes_by_ref.items()
        if ref not in owners and _penetrates(segment, box)
    ]


def _passes_through_pin(segments: list[_Segment], point: _MM) -> bool:
    """True if any segment's interior runs across ``point``."""
    px, py = point
    for x1, y1, x2, y2 in segments:
        if abs(y1 - y2) <= _EPS and abs(py - y1) <= _EPS:
            if min(x1, x2) + _EPS < px < max(x1, x2) - _EPS:
                return True
        if abs(x1 - x2) <= _EPS and abs(px - x1) <= _EPS:
            if min(y1, y2) + _EPS < py < max(y1, y2) - _EPS:
                return True
    return False


def _shares_geometry(one: _Segment, other: _Segment) -> bool:
    """True if two orthogonal segments touch or overlap.

    KiCad unions wires by geometry, so any contact merges the two nets even when
    the schematic declares them separately.
    """
    x1, y1, x2, y2 = one
    u1, v1, u2, v2 = other
    if abs(y1 - y2) <= _EPS and abs(v1 - v2) <= _EPS and abs(y1 - v1) <= _EPS:
        return max(min(x1, x2), min(u1, u2)) <= min(max(x1, x2), max(u1, u2)) + _EPS
    if abs(x1 - x2) <= _EPS and abs(u1 - u2) <= _EPS and abs(x1 - u1) <= _EPS:
        return max(min(y1, y2), min(v1, v2)) <= min(max(y1, y2), max(v1, v2)) + _EPS

    def on_wire(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> bool:
        if abs(ay - by) <= _EPS and abs(py - ay) <= _EPS:
            return min(ax, bx) - _EPS <= px <= max(ax, bx) + _EPS
        if abs(ax - bx) <= _EPS and abs(px - ax) <= _EPS:
            return min(ay, by) - _EPS <= py <= max(ay, by) + _EPS
        return False

    return (
        on_wire(x1, y1, u1, v1, u2, v2)
        or on_wire(x2, y2, u1, v1, u2, v2)
        or on_wire(u1, v1, x1, y1, x2, y2)
        or on_wire(u2, v2, x1, y1, x2, y2)
    )


def _distinct_nets(net_segments: dict[int, list[_Segment]]) -> int:
    """Count electrically distinct nets once KiCad unions wires by geometry."""
    parent = {net: net for net in net_segments}

    def find(net: int) -> int:
        while parent[net] != net:
            parent[net] = parent[parent[net]]
            net = parent[net]
        return net

    for left in net_segments:
        for right in net_segments:
            if right <= left:
                continue
            if any(_shares_geometry(a, b) for a in net_segments[left] for b in net_segments[right]):
                root_left, root_right = find(left), find(right)
                if root_left != root_right:
                    parent[root_right] = root_left
    return len({find(net) for net in net_segments})


def _random_nets(seed: int) -> list[list[dict[str, object]]]:
    """Partition every pin into independent nets (pairs, plus one triple).

    No two nets share a pin, so any geometry merge detected later is the
    router's doing rather than an artefact of the partition.
    """
    pins = list(_pins())
    random.Random(seed).shuffle(pins)  # noqa: S311 - deterministic test cases, not security
    nets: list[list[dict[str, object]]] = []
    index = 0
    while index < len(pins):
        take = 3 if len(pins) - index == 3 else 2
        nets.append(pins[index : index + take])
        index += take
    return nets


def _route_net(group: list[dict[str, object]], boxes: list[BBox]) -> list[_Segment]:
    """Route one net's pins together and collect its segments."""
    segments: list[_Segment] = []
    for target in group[1:]:
        routed, warning = _route_avoiding_obstacles(
            group[0]["point"],  # type: ignore[arg-type]
            target["point"],  # type: ignore[arg-type]
            boxes,
            True,
        )
        assert warning is None
        segments.extend(routed)
    return segments


# --------------------------------------------------------------------------- #
# 1. primitive-accurate symbol extents
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("symbol", "width", "height"), FIXTURE_EXTENTS)
def test_symbol_extent_matches_drawn_geometry(
    fixture_library: Path, symbol: str, width: float, height: float
) -> None:
    """Extents come from the symbol's graphics and pins, not a fixed guess."""
    bounds = get_symbol_primitive_bounds("Fixture", symbol, 100.0, 100.0, 0, 1)
    assert bounds is not None
    x_min, y_min, x_max, y_max = bounds
    assert x_max - x_min == pytest.approx(width, abs=1e-4)
    assert y_max - y_min == pytest.approx(height, abs=1e-4)


def test_capacitor_extent_covers_plates_beyond_its_collinear_pins(
    fixture_library: Path,
) -> None:
    """Both ``C`` pins sit on x = 0, so only the plates define the width."""
    pins = get_pin_positions("Fixture", "C", 0.0, 0.0, 0, 1)
    assert {round(px, 4) for px, _ in pins.values()} == {0.0}

    bounds = get_symbol_primitive_bounds("Fixture", "C", 0.0, 0.0, 0, 1)
    assert bounds is not None
    # A pin-only box would report zero width here.
    assert bounds[0] == pytest.approx(-2.032, abs=1e-4)
    assert bounds[2] == pytest.approx(2.032, abs=1e-4)


def test_transistor_extent_includes_the_enclosing_circle(fixture_library: Path) -> None:
    """Regression: the BJT circle reaches 4.0894 mm, past the 2.54 mm pins.

    A pin-only or rectangle-only box clipped the right crest of the circle, so
    the drawn transistor poked outside its own keepout.
    """
    pins = get_pin_positions("Fixture", "Q_NPN", 0.0, 0.0, 0, 1)
    pin_right_edge = max(px for px, _ in pins.values())
    assert pin_right_edge == pytest.approx(2.54, abs=1e-4)

    bounds = get_symbol_primitive_bounds("Fixture", "Q_NPN", 0.0, 0.0, 0, 1)
    assert bounds is not None
    assert bounds[2] == pytest.approx(4.0894, abs=1e-4)
    assert bounds[2] > pin_right_edge


def test_led_extent_includes_emission_arrows(fixture_library: Path) -> None:
    """LED arrows extend left of pin 1, which makes that pin asymmetric."""
    bounds = get_symbol_primitive_bounds("Fixture", "LED", 0.0, 0.0, 0, 1)
    assert bounds is not None
    pin_left_edge = min(
        px for px, _ in get_pin_positions("Fixture", "LED", 0.0, 0.0, 0, 1).values()
    )
    assert bounds[0] == pytest.approx(-4.572, abs=1e-4)
    assert bounds[0] < pin_left_edge


def test_extent_rotation_swaps_the_axes(fixture_library: Path) -> None:
    """A rotated placement must rotate the extents, not reuse the raw box."""
    upright = get_symbol_primitive_bounds("Fixture", "R", 100.0, 100.0, 0, 1)
    sideways = get_symbol_primitive_bounds("Fixture", "R", 100.0, 100.0, 90, 1)
    assert upright is not None and sideways is not None
    assert (upright[2] - upright[0], upright[3] - upright[1]) == pytest.approx(
        (2.032, 7.62), abs=1e-4
    )
    assert (sideways[2] - sideways[0], sideways[3] - sideways[1]) == pytest.approx(
        (7.62, 2.032), abs=1e-4
    )


def test_extent_returns_none_for_an_unknown_symbol(fixture_library: Path) -> None:
    """An unresolvable symbol lets the caller fall back instead of guessing."""
    assert get_symbol_primitive_bounds("Fixture", "NoSuchSymbol", 0.0, 0.0, 0, 1) is None
    assert get_symbol_primitive_bounds("NoSuchLibrary", "R", 0.0, 0.0, 0, 1) is None


@pytest.mark.parametrize("symbol", [symbol for symbol, _, _ in FIXTURE_EXTENTS])
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_extent_contains_every_pin(fixture_library: Path, symbol: str, rotation: int) -> None:
    """A keepout that excludes its own pins can never be routed from.

    This is the invariant the escape stub depends on: the pin must be inside (or
    on) the box so that stepping one grid unit outward clears it.
    """
    bounds = get_symbol_primitive_bounds("Fixture", symbol, 100.0, 100.0, rotation, 1)
    assert bounds is not None
    x_min, y_min, x_max, y_max = bounds
    for px, py in get_pin_positions("Fixture", symbol, 100.0, 100.0, rotation, 1).values():
        assert x_min - _EPS <= px <= x_max + _EPS
        assert y_min - _EPS <= py <= y_max + _EPS


def test_most_pins_sit_on_the_keepout_perimeter(fixture_library: Path) -> None:
    """Document the escape-stub precondition and its one known exception.

    ``P_escape = P_pin + normal * 1.27 mm`` clears the keepout only when the pin
    lies on the perimeter.  Every symbol here complies except ``LED`` pin 1,
    because its emission arrows push the box 0.762 mm past the pin.  The stub
    still clears it only because 1.27 mm > 0.762 mm -- a symbol whose graphic
    overhangs a pin by more than one grid unit would break the pattern, so the
    depth is asserted here rather than assumed.
    """
    on_perimeter: list[str] = []
    inside: dict[str, float] = {}
    for ref, symbol, x, y in SHEET:
        bounds = get_symbol_primitive_bounds("Fixture", symbol, x, y, 0, 1)
        assert bounds is not None
        x_min, y_min, x_max, y_max = bounds
        for number, (px, py) in get_pin_positions("Fixture", symbol, x, y, 0, 1).items():
            depth = min(px - x_min, x_max - px, py - y_min, y_max - py)
            if depth <= 1e-4:
                on_perimeter.append(f"{ref}.{number}")
            else:
                inside[f"{ref}.{number}"] = depth

    assert len(on_perimeter) == 20
    assert set(inside) == {"LED1.1"}
    # The only pin inside its keepout is still cleared by a single grid step.
    assert inside["LED1.1"] == pytest.approx(0.762, abs=1e-4)
    assert inside["LED1.1"] < SCHEMATIC_GRID_MM


# --------------------------------------------------------------------------- #
# 2. escape-and-route behaviour
# --------------------------------------------------------------------------- #
def test_clear_pins_take_the_direct_route() -> None:
    """Nothing in the way means no needless detour."""
    segments, warning = _route_avoiding_obstacles((0.0, 0.0), (10.16, 0.0), [], False)
    assert warning is None
    assert segments == [(0.0, 0.0, 10.16, 0.0)]


def test_symbol_without_any_geometry_has_no_extent(fixture_library: Path) -> None:
    """A part with neither graphics nor pins reports no extent.

    Returning ``None`` rather than a degenerate point box lets the caller fall
    back to the coarse estimate instead of routing against a zero-size keepout.
    """
    assert get_symbol_primitive_bounds("Fixture", "EMPTY", 0.0, 0.0, 0, 1) is None


def test_get_symbol_bboxes_prefers_primitives_and_falls_back(
    fixture_library: Path,
) -> None:
    """Placements resolve to tight keepouts, or to the coarse estimate.

    ``_get_symbol_bboxes`` is what turns a schematic into routing obstacles, so
    both paths matter: a resolvable library symbol must give the tight box, and
    an unresolvable one must still produce *a* box rather than nothing.
    """
    content = (
        "(kicad_sch\n"
        "\t(version 20231120)\n"
        '\t(uuid "11111111-1111-1111-1111-111111111111")\n'
        '\t(paper "A4")\n'
        '\t(symbol (lib_id "Fixture:R") (at 100 100 0) (unit 1)\n'
        '\t\t(uuid "22222222-2222-2222-2222-222222222222")\n'
        '\t\t(property "Reference" "R1" (at 102.032 100 90)'
        " (effects (font (size 1.27 1.27))))\n"
        "\t)\n"
        '\t(symbol (lib_id "Unknown:Thing") (at 200 100 0) (unit 1)\n'
        '\t\t(uuid "33333333-3333-3333-3333-333333333333")\n'
        '\t\t(property "Reference" "U9" (at 202 100 0)'
        " (effects (font (size 1.27 1.27))))\n"
        "\t)\n"
        ")\n"
    )

    boxes = _get_symbol_bboxes(content)

    assert len(boxes) == 2
    tight, coarse = boxes
    # Fixture:R is 2.032 x 7.62 mm around (100, 100).
    assert tight == pytest.approx(BBox(98.984, 96.19, 101.016, 103.81), abs=1e-4)
    # The unresolvable symbol falls back to the coarse estimate, never to nothing.
    assert coarse.x_max > coarse.x_min
    assert coarse.y_max > coarse.y_min


def test_segment_intersection_ignores_non_orthogonal_runs() -> None:
    """Only Manhattan runs are analysed, so a diagonal is reported as clear.

    Routing emits orthogonal segments only; treating diagonals as "no crossing"
    keeps the check from claiming a hit on geometry the router never produces.
    """
    box = BBox(0.0, 0.0, 10.0, 10.0)
    assert _segment_intersects_bbox((0.0, 0.0, 10.0, 10.0), box) is False
    assert _segment_intersects_bbox((0.0, 5.0, 10.0, 5.0), box) is True
    assert _segment_intersects_bbox((5.0, 0.0, 5.0, 10.0), box) is True


def test_symbol_without_unit_children_still_yields_an_extent(
    fixture_library: Path,
) -> None:
    """Primitives stored directly on the symbol root are parsed too.

    Flattened and imported symbols often carry their graphics and pins inline
    rather than in ``<name>_0_1`` / ``<name>_1_1`` child units; the extent parser
    must not silently return nothing for them.
    """
    bounds = get_symbol_primitive_bounds("Fixture", "FLAT", 0.0, 0.0, 0, 1)
    assert bounds == pytest.approx((-3.81, -1.27, 3.81, 1.27), abs=1e-4)


@pytest.mark.parametrize(
    ("pin", "owner", "expected"),
    [
        ((2.0, 0.0), BBox(0.0, 0.0, 4.0, 8.0), (0.0, -1.0)),
        ((2.0, 8.0), BBox(0.0, 0.0, 4.0, 8.0), (0.0, 1.0)),
        ((0.0, 4.0), BBox(0.0, 0.0, 4.0, 8.0), (-1.0, 0.0)),
        ((4.0, 4.0), BBox(0.0, 0.0, 4.0, 8.0), (1.0, 0.0)),
    ],
)
def test_escape_direction_points_out_of_the_pins_own_edge(
    pin: _MM, owner: BBox, expected: _MM
) -> None:
    """Each perimeter pin escapes through the edge it sits on."""
    assert schematic_module._escape_direction(pin, owner) == expected


def test_escape_direction_leaves_an_interior_pin_by_the_nearest_edge() -> None:
    """A pin buried by an overhanging graphic still escapes the short way."""
    owner = BBox(0.0, 0.0, 10.0, 10.0)
    assert schematic_module._escape_direction((0.5, 5.0), owner) == (-1.0, 0.0)
    assert schematic_module._escape_direction((5.0, 9.5), owner) == (0.0, 1.0)


def test_route_reports_a_warning_when_no_path_exists() -> None:
    """An unreachable target must fail loudly instead of pretending to route.

    The end escape point is sealed inside a ring of keepouts, so A* exhausts the
    grid.  The function then hands back the direct run together with an
    ``obstacle_bypass_failed`` warning: that run may cross a keepout, which is
    precisely why the warning exists for the caller to escalate.
    """
    start_owner = BBox(0.0, 0.0, 4.0, 8.0)
    end_owner = BBox(20.0, 0.0, 24.0, 8.0)
    ring = [
        BBox(16.0, -6.0, 30.0, -4.0),
        BBox(16.0, 2.0, 30.0, 4.0),
        BBox(16.0, -6.0, 18.0, 4.0),
        BBox(28.0, -6.0, 30.0, 4.0),
    ]

    segments, warning = _route_avoiding_obstacles(
        (2.0, 0.0), (22.0, 0.0), [start_owner, end_owner, *ring], True
    )

    assert warning is not None
    assert "obstacle_bypass_failed" in warning
    assert segments


def test_route_escapes_one_grid_step_along_the_outward_normal(
    boxes_by_ref: dict[str, BBox],
) -> None:
    """R1 pin 1 and LED1 pin 2 are joined above the capacitor between them.

    Pin 1 of the fixture resistor sits on the top edge, so the stub must be
    exactly one 1.27 mm grid step in -Y before any horizontal travel happens.
    """
    start, end = _pin("R1", "1"), _pin("C1", "1")
    segments, warning = _route_avoiding_obstacles(start, end, list(boxes_by_ref.values()), True)

    assert warning is None
    # Compare against the router's own grid snap so the stub endpoint matches
    # bit for bit rather than within a floating point tolerance.
    _, stub_y = _snap_point(start[0], start[1] - SCHEMATIC_GRID_MM, True)
    assert (start[0], stub_y, start[0], start[1]) in segments
    assert (end[0], stub_y, end[0], end[1]) in segments
    # Travel happens on the escape row, clear of every intervening body.
    assert any(abs(s[1] - stub_y) <= _EPS and abs(s[3] - stub_y) <= _EPS for s in segments)
    assert not _foreign_crossings(segments, boxes_by_ref, {"R1", "C1"})


def test_route_never_penetrates_an_intervening_component(
    boxes_by_ref: dict[str, BBox],
) -> None:
    """A wire spanning the sheet must go around the symbols, not through them."""
    segments, warning = _route_avoiding_obstacles(
        _pin("R1", "1"), _pin("Q1", "C"), list(boxes_by_ref.values()), True
    )

    assert warning is None
    assert segments
    assert not _foreign_crossings(segments, boxes_by_ref, {"R1", "Q1"})


def test_route_does_not_run_across_another_component_pin(
    boxes_by_ref: dict[str, BBox],
) -> None:
    """A wire must never short onto a foreign pin.

    ``C1`` sits directly between ``R1`` and ``LED1``, and its pin 1 lies on the
    same row as theirs.  A route that hugged the keepout edge would run straight
    through that pin and merge both nets.
    """
    segments, warning = _route_avoiding_obstacles(
        _pin("R1", "1"), _pin("LED1", "2"), list(boxes_by_ref.values()), True
    )

    assert warning is None
    for ref, symbol, x, y in SHEET:
        if ref in {"R1", "LED1"}:
            continue
        for number, position in get_pin_positions("Fixture", symbol, x, y, 0, 1).items():
            assert not _passes_through_pin(segments, position), f"route crosses {ref}.{number}"


def test_long_cross_sheet_route_is_within_the_search_budget(
    boxes_by_ref: dict[str, BBox],
) -> None:
    """Regression: a long crossing used to exhaust the A* step budget.

    The router gave up and fell back to a straight line through the symbols.
    """
    start, end = _pin("R1", "2"), _pin("U2", "8")
    segments, warning = _route_avoiding_obstacles(start, end, list(boxes_by_ref.values()), True)

    assert warning is None
    assert segments
    assert abs(start[0] - end[0]) + abs(start[1] - end[1]) > 100.0
    assert not _foreign_crossings(segments, boxes_by_ref, {"R1", "U2"})


def test_escape_route_replaces_the_padded_keepout_trap(
    boxes_by_ref: dict[str, BBox],
) -> None:
    """Regression: 5.0 mm of padding used to bury the pin inside its own box.

    With every symbol inflated by 5.0 mm the start pin sat several mm inside an
    obstacle, so A* found all four neighbours blocked and abandoned on step one,
    returning ``WARNING: obstacle_bypass_failed`` plus a straight line that cut
    through the component.  The escape strategy must produce a clean detour.
    """
    start, end = _pin("R1", "1"), _pin("C1", "1")
    boxes = list(boxes_by_ref.values())

    padded = [BBox(b.x_min - 5, b.y_min - 5, b.x_max + 5, b.y_max + 5) for b in boxes]
    assert any(b.x_min <= start[0] <= b.x_max and b.y_min <= start[1] <= b.y_max for b in padded), (
        "precondition: the padded box is expected to swallow the start pin"
    )

    segments, warning = _route_avoiding_obstacles(start, end, boxes, True)

    assert warning is None
    assert len(segments) >= 3
    assert not _foreign_crossings(segments, boxes_by_ref, {"R1", "C1"})


def test_single_net_route_is_self_consistent(boxes_by_ref: dict[str, BBox]) -> None:
    """Over random partitions, every route stays orthogonal and body-clear."""
    boxes = list(boxes_by_ref.values())
    for seed in range(4):
        for group in _random_nets(seed):
            segments = _route_net(group, boxes)
            owners = {str(group[0]["ref"]), *(str(t["ref"]) for t in group[1:])}
            for x1, y1, x2, y2 in segments:
                assert abs(x1 - x2) <= _EPS or abs(y1 - y2) <= _EPS, "wire is not orthogonal"
            assert not _foreign_crossings(segments, boxes_by_ref, owners)


# --------------------------------------------------------------------------- #
# 3. known defect: the router has no inter-net awareness
# --------------------------------------------------------------------------- #
@pytest.mark.xfail(
    strict=True,
    reason=(
        "Router lacks inter-net awareness: each net is routed independently "
        "against component keepouts only, so independent nets converge on the "
        "same lowest-cost channels and merge by geometry in KiCad (silent "
        "short). Measured on a 10-symbol sheet over 40 random partitions: 15 "
        "intended nets collapse to a mean of 3.5, and to 1 at the worst seed. "
        "Removing this marker requires per-net occupancy or a net-aware dedup "
        "guard on collinear segments owned by different nets."
    ),
)
def test_router_lacks_inter_net_awareness(boxes_by_ref: dict[str, BBox]) -> None:
    """Independent nets must survive geometry union as distinct nets."""
    boxes = list(boxes_by_ref.values())
    for seed in range(4):
        nets = _random_nets(seed)
        net_segments = {
            index: _route_net(group, boxes) for index, group in enumerate(nets, start=1)
        }
        distinct = _distinct_nets(net_segments)
        assert net_segments
        assert distinct == len(nets), (
            f"seed {seed}: {len(nets)} independent nets collapsed to {distinct} "
            f"after KiCad unions wires by geometry"
        )


# --------------------------------------------------------------------------- #
# 4. the same properties against the genuinely installed KiCad libraries
# --------------------------------------------------------------------------- #
requires_kicad_library = pytest.mark.skipif(
    _symbol_library_file("Device") is None,
    reason="KiCad symbol libraries are not installed on this machine",
)

#: ``(library, symbol, width_mm, height_mm)`` from the real KiCad libraries.
REAL_EXTENTS: list[tuple[str, str, float, float]] = [
    ("Device", "R", 2.032, 7.62),
    ("Device", "C", 4.064, 7.62),
    ("Device", "L", 0.6323, 7.62),
    ("Device", "D", 7.62, 2.54),
    ("Device", "LED", 8.382, 3.556),
    ("Device", "Q_NPN", 9.1694, 10.16),
    ("Connector_Generic", "Conn_01x04", 6.35, 10.16),
    ("Amplifier_Operational", "LM358", 15.24, 10.16),
    ("Timer", "NE555P", 20.32, 20.32),
    ("Regulator_Linear", "AMS1117-3.3", 15.24, 9.525),
]


@requires_kicad_library
@pytest.mark.parametrize(("library", "symbol", "width", "height"), REAL_EXTENTS)
def test_real_library_extent_matches_drawn_geometry(
    library: str, symbol: str, width: float, height: float
) -> None:
    """The shipped KiCad symbols produce the same tight extents."""
    bounds = get_symbol_primitive_bounds(library, symbol, 100.0, 100.0, 0, 1)
    assert bounds is not None
    x_min, y_min, x_max, y_max = bounds
    assert x_max - x_min == pytest.approx(width, abs=1e-4)
    assert y_max - y_min == pytest.approx(height, abs=1e-4)


@requires_kicad_library
@pytest.mark.parametrize(("library", "symbol"), [(lib, sym) for lib, sym, _, _ in REAL_EXTENTS])
def test_real_library_extent_contains_every_pin(library: str, symbol: str) -> None:
    """The shipped KiCad symbols keep their pins inside their own keepout."""
    bounds = get_symbol_primitive_bounds(library, symbol, 100.0, 100.0, 0, 1)
    assert bounds is not None
    x_min, y_min, x_max, y_max = bounds
    for px, py in get_pin_positions(library, symbol, 100.0, 100.0, 0, 1).values():
        assert x_min - _EPS <= px <= x_max + _EPS
        assert y_min - _EPS <= py <= y_max + _EPS
