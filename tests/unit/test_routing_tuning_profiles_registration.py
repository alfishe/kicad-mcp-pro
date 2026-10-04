from __future__ import annotations

import importlib
import importlib.util
import inspect
from types import ModuleType

from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.routing_tuning_profiles")
    assert spec is not None, "Routing tuning-profile adapter module must be extracted"
    return importlib.import_module("kicad_mcp.tools.routing_tuning_profiles")


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def create(
        self,
        name: str,
        layer: str,
        trace_impedance_ohm: float,
        propagation_speed_factor: float,
    ) -> str:
        self.calls.append(("create", name, layer, trace_impedance_ohm, propagation_speed_factor))
        return "created-profile"

    def list_profiles(self) -> str:
        self.calls.append(("list",))
        return '{"fast": {}}'

    def apply(self, net_pattern: str, profile_name: str) -> str:
        self.calls.append(("apply", net_pattern, profile_name))
        return "applied-profile"


def test_registration_preserves_order_signatures_metadata_and_delegation() -> None:
    adapter = _adapter()
    server = FastMCP("routing-tuning-profile-registration")
    service = FakeService()

    adapter.register(
        server,
        adapter.RoutingTuningProfileDependencies(service=service),
    )

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == [
        "route_create_tuning_profile",
        "route_list_tuning_profiles",
        "route_apply_tuning_profile",
    ]

    create, list_profiles, apply = tools
    assert str(inspect.signature(create.fn)) == (
        "(name: 'str', layer: 'str', trace_impedance_ohm: 'float', "
        "propagation_speed_factor: 'float') -> 'str'"
    )
    assert str(inspect.signature(list_profiles.fn)) == "() -> 'str'"
    assert str(inspect.signature(apply.fn)) == (
        "(net_pattern: 'str', profile_name: 'str') -> 'str'"
    )
    assert "Create or update a KiCad 10-style time-domain tuning profile" in (
        create.fn.__doc__ or ""
    )
    assert "List configured time-domain tuning profiles" in (list_profiles.fn.__doc__ or "")
    assert "Assign a named tuning profile" in (apply.fn.__doc__ or "")

    for tool_name in (
        "route_create_tuning_profile",
        "route_list_tuning_profiles",
        "route_apply_tuning_profile",
    ):
        metadata = get_tool_metadata(tool_name)
        assert metadata is not None
        assert metadata.headless_compatible is True
        assert metadata.requires_kicad_running is False

    assert create.fn("fast", "F.Cu", 90.0, 0.6) == "created-profile"
    assert list_profiles.fn() == '{"fast": {}}'
    assert apply.fn("DATA*", "fast") == "applied-profile"
    assert service.calls == [
        ("create", "fast", "F.Cu", 90.0, 0.6),
        ("list",),
        ("apply", "DATA*", "fast"),
    ]
