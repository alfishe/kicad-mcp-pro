from __future__ import annotations

import importlib
import importlib.util
import inspect
from types import ModuleType

from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.models.tool_result import ToolResult
from kicad_mcp.tools.metadata import get_tool_metadata


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.routing_specctra_staging")
    assert spec is not None, "Routing Specctra staging adapter module must be extracted"
    return importlib.import_module("kicad_mcp.tools.routing_specctra_staging")


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def export_dsn(self, output_path: str) -> ToolResult:
        self.calls.append(("export", output_path))
        return ToolResult.success("route_export_dsn", changed=True)

    def import_ses(self, ses_path: str) -> ToolResult:
        self.calls.append(("import", ses_path))
        return ToolResult.success("route_import_ses", changed=False)


def test_registration_preserves_order_signatures_metadata_and_delegation() -> None:
    adapter = _adapter()
    server = FastMCP("routing-specctra-staging-registration")
    service = FakeService()

    adapter.register(
        server,
        adapter.RoutingSpecctraStagingDependencies(service=service),
    )

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == [
        "route_export_dsn",
        "route_import_ses",
    ]

    export, import_ses = tools
    assert str(inspect.signature(export.fn)) == (
        "(output_path: 'str' = 'output/routing/board.dsn') -> 'ToolResult'"
    )
    assert str(inspect.signature(import_ses.fn)) == (
        "(ses_path: 'str' = 'output/routing/board.ses') -> 'ToolResult'"
    )
    assert "Export a Specctra DSN for FreeRouting" in (export.fn.__doc__ or "")
    assert "Stage a routed Specctra SES" in (import_ses.fn.__doc__ or "")

    for tool_name in ("route_export_dsn", "route_import_ses"):
        metadata = get_tool_metadata(tool_name)
        assert metadata is not None
        assert metadata.headless_compatible is True
        assert metadata.requires_kicad_running is False

    assert export.fn("custom/board.dsn").tool_name == "route_export_dsn"
    assert import_ses.fn("custom/board.ses").tool_name == "route_import_ses"
    assert service.calls == [
        ("export", "custom/board.dsn"),
        ("import", "custom/board.ses"),
    ]
