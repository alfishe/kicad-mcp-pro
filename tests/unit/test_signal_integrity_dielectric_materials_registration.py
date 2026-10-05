from __future__ import annotations

import importlib
import inspect

from mcp.server.mcpserver import MCPServer as FastMCP


class FakeService:
    def __init__(self) -> None:
        self.calls = 0

    def list_materials(self) -> str:
        self.calls += 1
        return "materials-result"


def test_registration_preserves_signature_docstring_and_delegation() -> None:
    adapter = importlib.import_module("kicad_mcp.tools.signal_integrity_dielectric_materials")
    server = FastMCP("si-dielectric-materials-registration")
    service = FakeService()

    adapter.register(
        server,
        adapter.SignalIntegrityDielectricMaterialsDependencies(service=service),
    )

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["si_list_dielectric_materials"]

    tool = tools[0]
    assert str(inspect.signature(tool.fn)) == "() -> 'str'"
    assert "List all built-in dielectric materials" in (tool.fn.__doc__ or "")
    assert "si_synthesize_stackup_for_interfaces" in (tool.fn.__doc__ or "")

    assert tool.fn() == "materials-result"
    assert service.calls == 1
