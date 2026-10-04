from __future__ import annotations

import importlib
import inspect

from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.models.tool_result import ToolResult
from kicad_mcp.tools.metadata import get_tool_metadata


class FakeService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def apply(self, ses_path: str) -> ToolResult:
        self.calls.append(ses_path)
        return ToolResult.success("route_apply_ses", changed=True)


def test_registration_preserves_signature_metadata_and_delegation() -> None:
    adapter = importlib.import_module("kicad_mcp.tools.routing_ses_apply")
    server = FastMCP("routing-ses-apply-registration")
    service = FakeService()

    adapter.register(server, adapter.RoutingSesApplyDependencies(service=service))

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["route_apply_ses"]
    tool = tools[0]
    assert str(inspect.signature(tool.fn)) == (
        "(ses_path: 'str' = 'output/routing/board.ses') -> 'ToolResult'"
    )
    metadata = get_tool_metadata("route_apply_ses")
    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False
    assert tool.fn("custom/board.ses").tool_name == "route_apply_ses"
    assert service.calls == ["custom/board.ses"]
