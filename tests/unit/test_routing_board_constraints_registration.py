from __future__ import annotations

import importlib
import importlib.util
import inspect
from types import ModuleType

from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.models.tool_result import ToolResult
from kicad_mcp.tools.metadata import get_tool_metadata


def _adapter() -> ModuleType:
    module_name = "kicad_mcp.tools.routing_board_constraints"
    spec = importlib.util.find_spec(module_name)
    assert spec is not None
    return importlib.import_module(module_name)


class FakeService:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self) -> ToolResult:
        self.calls += 1
        return ToolResult.success("generate_board_constraints", changed=True)


def test_registration_preserves_signature_metadata_docstring_and_delegation() -> None:
    adapter = _adapter()
    server = FastMCP("routing-board-constraints-registration")
    service = FakeService()

    adapter.register(
        server,
        adapter.RoutingBoardConstraintsDependencies(service=service),
    )

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["generate_board_constraints"]
    tool = tools[0]
    assert str(inspect.signature(tool.fn)) == "() -> 'ToolResult'"
    assert "Generate .kicad_dru rules and net-class constraints" in (tool.fn.__doc__ or "")
    metadata = get_tool_metadata("generate_board_constraints")
    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False

    assert tool.fn().tool_name == "generate_board_constraints"
    assert service.calls == 1


def test_dependency_factory_preserves_injected_callbacks() -> None:
    adapter = _adapter()
    calls: list[str] = []
    deps = adapter.dependencies(
        load_design_intent=lambda: calls.append("load") or SimpleIntent(),
        write_rule=lambda name, body: calls.append(f"write:{name}") or PathLike(),
    )

    result = deps.service.generate()

    assert result.ok is False
    assert calls == ["load"]


class SimpleIntent:
    power_rails: list[object] = []
    interfaces: list[object] = []


class PathLike:
    def __str__(self) -> str:
        return "unused.kicad_dru"
