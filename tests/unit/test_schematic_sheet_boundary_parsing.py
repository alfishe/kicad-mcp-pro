"""Parsing layer: sheets and drawn rectangles become routing boundaries.

The routing rules themselves are covered by ``test_schematic_router_behaviour``,
which exercises the predicates on bare grids.  What is covered *here* is the
parsing that feeds them -- and that layer is where the interesting failures live,
because a predicate that is correct on the wrong rectangles is still wrong.

Both directions are asserted throughout: a thing that should be found is found,
and a thing that should be ignored is ignored.  A test that only checks the first
passes on a parser that returns everything it sees.

Concretely, this file exists because a coverage gate noticed that
``get_sheet_pin_outward_normals`` and ``_get_sheet_bboxes`` were **entirely**
unexercised while the rules built on them were not -- the predicates had tests and
the parsers had none.
"""

from __future__ import annotations

from kicad_mcp.schematic.sheet_pins import outward_normal_for_rotation
from kicad_mcp.tools.schematic import (
    _get_module_boundaries,
    _get_sheet_bboxes,
    _matching_paren,
    _sheet_graphic_rectangles,
    get_sheet_pin_outward_normals,
)

#: A sheet whose pins sit one per edge, so every rotation has a distinct answer.
SHEET_TEXT = """(kicad_sch (version 20231120)
\t(sheet
\t\t(at 80.01 30.48)
\t\t(size 30.48 20.32)
\t\t(property "Sheetname" "02_mcu"
\t\t\t(at 80.01 29.77 0)
\t\t)
\t\t(property "Sheetfile" "child.kicad_sch"
\t\t\t(at 80.01 51.38 0)
\t\t)
\t\t(pin "WEST" input (at 80.01 35.56 180)
\t\t\t(uuid 11111111-1111-1111-1111-111111111111)
\t\t)
\t\t(pin "EAST" output (at 110.49 35.56 0)
\t\t\t(uuid 22222222-2222-2222-2222-222222222222)
\t\t)
\t)
)
"""

#: A zero-sized sheet is unaddressable and must be skipped, not returned as a
#: degenerate box that every route would then be measured against.
DEGENERATE_SHEET_TEXT = """(kicad_sch (version 20231120)
\t(sheet
\t\t(at 10 10)
\t\t(size 0 0)
\t\t(property "Sheetname" "collapsed"
\t\t\t(at 10 9 0)
\t\t)
\t\t(property "Sheetfile" "collapsed.kicad_sch"
\t\t\t(at 10 20 0)
\t\t)
\t)
)
"""


def test_sheet_pin_normals_are_read_from_each_pins_rotation() -> None:
    """A sheet pin's escape direction comes from its rotation, not from geometry.

    A pin sits *on* its sheet's outline, so the nearest-edge heuristic gives
    distance zero to the edge it is on -- no usable signal.  The rotation is the
    only thing that distinguishes a pin on the west edge from one on the east.
    """
    normals = get_sheet_pin_outward_normals(SHEET_TEXT)

    assert normals[(80.01, 35.56)] == outward_normal_for_rotation(180) == (-1.0, 0.0)
    assert normals[(110.49, 35.56)] == outward_normal_for_rotation(0) == (1.0, 0.0)
    assert len(normals) == 2, f"expected one normal per pin, got {normals}"


def test_sheet_pin_normals_are_keyed_by_position() -> None:
    """Keyed by coordinate, because a sheet pin has no reference to look up by."""
    normals = get_sheet_pin_outward_normals(SHEET_TEXT)

    assert set(normals) == {(80.01, 35.56), (110.49, 35.56)}


def test_sheet_rectangle_becomes_a_keepout_box() -> None:
    """Origin plus size, not the centre: a sheet's ``(at ...)`` is its top-left."""
    boxes = _get_sheet_bboxes(SHEET_TEXT)

    assert len(boxes) == 1
    box = boxes[0]
    assert (box.x_min, box.y_min) == (80.01, 30.48)
    assert (round(box.x_max, 4), round(box.y_max, 4)) == (110.49, 50.8)


def test_a_collapsed_sheet_is_skipped_rather_than_returned_degenerate() -> None:
    """A zero-sized sheet cannot be addressed, so it is not a boundary."""
    assert _get_sheet_bboxes(DEGENERATE_SHEET_TEXT) == []
    assert get_sheet_pin_outward_normals(DEGENERATE_SHEET_TEXT) == {}


def test_matching_paren_finds_the_close_of_a_nested_node() -> None:
    """The scanner walks depth, so an inner node's ``)`` is not the answer."""
    text = "(outer (inner (deepest 1) 2) 3)"
    assert _matching_paren(text, 0) == len(text) - 1
    assert _matching_paren(text, text.index("(inner")) == text.index(") 3")


def test_a_paren_inside_a_quoted_string_is_not_counted() -> None:
    """KiCad writes label text verbatim, so a title can contain a bare paren.

    Counting it would unbalance the scan and the reported close would be wrong --
    which silently truncates or over-extends whatever the caller slices out.
    """
    text = '(node (text "a trap ) here") (real 1))'
    close = _matching_paren(text, 0)

    assert close == len(text) - 1
    assert text[close] == ")"
    assert text[: close + 1].count('"') == 2


def test_an_escaped_quote_does_not_end_the_string_early() -> None:
    """A backslash-escaped quote is part of the string, not its terminator."""
    text = r'(node (text "say \" ) loudly") (real 1))'

    assert _matching_paren(text, 0) == len(text) - 1


def test_only_rectangles_drawn_on_the_sheet_are_collected() -> None:
    """Symbol bodies are also ``(rectangle ...)`` and must not become boundaries.

    Every library symbol carries at least one, so collecting them at any depth
    would fence off the entire sheet.
    """
    text = """(kicad_sch (version 20231120)
\t(symbol
\t\t(lib_id "Device:R")
\t\t(rectangle (start 1 2) (end 3 4)
\t\t\t(stroke (width 0.254) (type default))
\t\t)
\t)
\t(rectangle (start 10 20) (end 40 60)
\t\t(stroke (width 0) (type default))
\t)
)
"""

    assert _sheet_graphic_rectangles(text) == [(10.0, 20.0, 40.0, 60.0)]


def test_a_rectangle_with_reversed_corners_is_normalised() -> None:
    """Bounds are min/max, so the order the corners were written in cannot matter."""
    text = """(kicad_sch (version 20231120)
\t(rectangle (start 40 60) (end 10 20)
\t\t(stroke (width 0) (type default))
\t)
)
"""

    assert _sheet_graphic_rectangles(text) == [(10.0, 20.0, 40.0, 60.0)]


def test_module_boundaries_are_the_sheets_plus_the_drawn_rectangles() -> None:
    """Both kinds of drawn boundary, because both mean "a block of its own"."""
    text = """(kicad_sch (version 20231120)
\t(sheet
\t\t(at 80.01 30.48)
\t\t(size 30.48 20.32)
\t\t(property "Sheetname" "02_mcu"
\t\t\t(at 80.01 29.77 0)
\t\t)
\t\t(property "Sheetfile" "child.kicad_sch"
\t\t\t(at 80.01 51.38 0)
\t\t)
\t)
\t(rectangle (start 10 20) (end 40 60)
\t\t(stroke (width 0) (type default))
\t)
)
"""

    boundaries = _get_module_boundaries(text)

    assert len(boundaries) == 2, f"expected sheet + drawing, got {boundaries}"
    assert (boundaries[0].x_min, boundaries[0].y_min) == (80.01, 30.48)
    assert (boundaries[1].x_min, boundaries[1].y_min) == (10.0, 20.0)
