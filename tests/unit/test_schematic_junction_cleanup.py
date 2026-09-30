"""A junction dot lives exactly as long as a wire ends on it.

Deleting a wire used to leave its junctions behind.  The dot that marked a T no
longer joins anything, and it is worse than cosmetic: the missing-junction repair
treats a point that already carries a junction as correct, so a stale dot
actively suppresses the junction that belongs there.  A junction with no wire
*ending* on it holds nothing together -- a crossing is not a connection in KiCad
-- so it is removed.
"""

from __future__ import annotations

from kicad_mcp.schematic.destructive_edit import (
    strip_junctions_without_wire_ends,
)
from kicad_mcp.tools.schematic import _extract_block, _extract_wires

_SHEET_WITH_JUNCTIONS = """(kicad_sch (version 20231120)
\t(junction (at 10 10) (diameter 0) (color 0 0 0 0) (uuid 1111))
\t(junction (at 20 20) (diameter 0) (color 0 0 0 0) (uuid 2222))
\t(wire (pts (xy 10 10) (xy 10 20)) (uuid 3333))
\t(wire (pts (xy 30 20) (xy 30 30)) (uuid 4444))
)
"""


def _strip(text: str) -> tuple[str, int]:
    """Run the rule with the real wire and block readers."""
    return strip_junctions_without_wire_ends(text, _extract_wires, _extract_block)


def test_junction_is_dropped_when_no_wire_ends_on_it() -> None:
    """Deleting a wire leaves its dot behind, which is worse than cosmetic.

    A stale dot suppresses the missing-junction repair: the fixer treats a point
    that already carries a junction as correct.  So a dot with no wire end on it
    has to go, or the repair that belongs there never happens.
    """
    text, dropped = _strip(_SHEET_WITH_JUNCTIONS)

    assert dropped == 1
    assert "20 20" not in text, "the orphaned junction survived"
    assert "10 10" in text, "the junction a wire still ends on was removed"


def test_junction_survives_while_any_wire_end_lands_on_it() -> None:
    """A junction is kept iff a wire *end* lands on it."""
    text, dropped = _strip(_SHEET_WITH_JUNCTIONS)

    assert dropped == 1
    assert text.count("(junction") == 1
