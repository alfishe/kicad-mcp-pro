from __future__ import annotations

import importlib
import inspect

from mcp.server.mcpserver import MCPServer as FastMCP


class FakeService:
    def __init__(self) -> None:
        self.calls = 0

    def report(self) -> str:
        self.calls += 1
        return "solver-capabilities-result"


def test_registration_preserves_signature_docstring_order_and_delegation() -> None:
    adapter = importlib.import_module("kicad_mcp.tools.signal_integrity_solver_capabilities")
    server = FastMCP("si-solver-capabilities-registration")
    service = FakeService()

    adapter.register(
        server,
        adapter.SignalIntegritySolverCapabilitiesDependencies(service=service),
    )

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["si_get_solver_capabilities"]

    tool = tools[0]
    assert str(inspect.signature(tool.fn)) == "() -> 'str'"
    assert (
        tool.fn.__doc__
        == "Report configured solver-grade analysis capabilities and unavailable seams."
    )
    assert tool.fn() == "solver-capabilities-result"
    assert service.calls == 1
