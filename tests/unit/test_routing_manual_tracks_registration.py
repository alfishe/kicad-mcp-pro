from __future__ import annotations

import importlib
import importlib.util
import inspect
from types import ModuleType

from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.routing_manual_tracks")
    assert spec is not None
    return importlib.import_module("kicad_mcp.tools.routing_manual_tracks")


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def route_single(
        self,
        x1_mm: float,
        y1_mm: float,
        x2_mm: float,
        y2_mm: float,
        layer: str = "F_Cu",
        width_mm: float = 0.25,
        net_name: str = "",
    ) -> str:
        self.calls.append(("single", x1_mm, y1_mm, x2_mm, y2_mm, layer, width_mm, net_name))
        return "single-delegated"

    def route_pad_to_pad(
        self,
        ref1: str,
        pad1: str,
        ref2: str,
        pad2: str,
        layer: str = "F_Cu",
        width_mm: float = 0.25,
    ) -> str:
        self.calls.append(("pads", ref1, pad1, ref2, pad2, layer, width_mm))
        return "pads-delegated"


def test_registration_preserves_order_signatures_metadata_and_delegation() -> None:
    adapter = _adapter()
    server = FastMCP("routing-manual-track-registration")
    service = FakeService()

    adapter.register(
        server,
        adapter.RoutingManualTrackDependencies(service=service),
    )

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == [
        "route_single_track",
        "route_from_pad_to_pad",
    ]

    single, pads = tools
    assert str(inspect.signature(single.fn)) == (
        "(x1_mm: 'float', y1_mm: 'float', x2_mm: 'float', y2_mm: 'float', "
        "layer: 'str' = 'F_Cu', width_mm: 'float' = 0.25, "
        "net_name: 'str' = '') -> 'str'"
    )
    assert str(inspect.signature(pads.fn)) == (
        "(ref1: 'str', pad1: 'str', ref2: 'str', pad2: 'str', "
        "layer: 'str' = 'F_Cu', width_mm: 'float' = 0.25) -> 'str'"
    )
    assert "Route a single straight track segment" in (single.fn.__doc__ or "")
    assert "Create a simple orthogonal route between two pads" in (pads.fn.__doc__ or "")

    for tool_name in ("route_single_track", "route_from_pad_to_pad"):
        metadata = get_tool_metadata(tool_name)
        assert metadata is not None
        assert metadata.headless_compatible is False
        assert metadata.requires_kicad_running is True

    assert single.fn(1.0, 2.0, 3.0, 4.0, "F_Cu", 0.3, "DATA") == "single-delegated"
    assert pads.fn("R1", "1", "U2", "3", "F_Cu", 0.25) == "pads-delegated"
    assert service.calls == [
        ("single", 1.0, 2.0, 3.0, 4.0, "F_Cu", 0.3, "DATA"),
        ("pads", "R1", "1", "U2", "3", "F_Cu", 0.25),
    ]
