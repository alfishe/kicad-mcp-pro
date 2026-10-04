from __future__ import annotations

import importlib
import importlib.util
import inspect
from types import ModuleType

from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata


def _single_adapter() -> ModuleType:
    module_name = "kicad_mcp.tools.routing_length_tuning"
    spec = importlib.util.find_spec(module_name)
    assert spec is not None
    return importlib.import_module(module_name)


def _pair_adapter() -> ModuleType:
    module_name = "kicad_mcp.tools.routing_diff_pair_length"
    spec = importlib.util.find_spec(module_name)
    assert spec is not None
    return importlib.import_module(module_name)


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def tune_net(
        self,
        net_name: str,
        target_mm: float,
        meander_amplitude_mm: float,
        tolerance_mm: float,
    ) -> str:
        self.calls.append(("single", net_name, target_mm, meander_amplitude_mm, tolerance_mm))
        return "single-delegated"

    def tune_diff_pair(
        self,
        net_name_p: str,
        net_name_n: str,
        target_length_mm: float,
    ) -> str:
        self.calls.append(("pair", net_name_p, net_name_n, target_length_mm))
        return "pair-delegated"


def test_single_registration_preserves_signature_metadata_and_delegation() -> None:
    adapter = _single_adapter()
    server = FastMCP("routing-length-tuning-registration")
    service = FakeService()
    adapter.register(server, adapter.RoutingLengthTuningDependencies(service=service))

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["route_tune_length"]
    tool = tools[0]
    assert str(inspect.signature(tool.fn)) == (
        "(net_name: 'str', target_mm: 'float', meander_amplitude_mm: 'float' = 0.5, "
        "tolerance_mm: 'float' = 0.1) -> 'str'"
    )
    assert "Write a length-tuning rule and report the current delta" in (tool.fn.__doc__ or "")
    metadata = get_tool_metadata("route_tune_length")
    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False

    assert tool.fn("CLK", 45.0, 0.75, 0.2) == "single-delegated"
    assert service.calls == [("single", "CLK", 45.0, 0.75, 0.2)]


def test_pair_registration_preserves_signature_metadata_and_delegation() -> None:
    adapter = _pair_adapter()
    server = FastMCP("routing-diff-pair-length-registration")
    service = FakeService()
    adapter.register(server, adapter.RoutingDiffPairLengthDependencies(service=service))

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["tune_diff_pair_length"]
    tool = tools[0]
    assert str(inspect.signature(tool.fn)) == (
        "(net_name_p: 'str', net_name_n: 'str', target_length_mm: 'float') -> 'str'"
    )
    assert "Write matched-length rules for both nets" in (tool.fn.__doc__ or "")
    metadata = get_tool_metadata("tune_diff_pair_length")
    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False

    assert tool.fn("USB_DP", "USB_DN", 51.0) == "pair-delegated"
    assert service.calls == [("pair", "USB_DP", "USB_DN", 51.0)]
