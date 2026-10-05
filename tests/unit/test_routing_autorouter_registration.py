from __future__ import annotations

import importlib
import inspect

import pytest
from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.models.tool_result import ToolResult
from kicad_mcp.tools.metadata import get_tool_metadata


class FakeService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def autoroute(self, **kwargs: object) -> ToolResult:
        self.calls.append(kwargs)
        reporter = kwargs["report_progress"]
        await reporter(10, 100, "test")
        return ToolResult.success("route_autoroute_freerouting", changed=False)


class FakeContext:
    def __init__(self) -> None:
        self.progress: list[tuple[float, float, str]] = []

    async def report_progress(self, progress: float, total: float, message: str) -> None:
        self.progress.append((progress, total, message))


@pytest.mark.anyio
async def test_registration_preserves_signature_metadata_dependency_and_delegation() -> None:
    adapter = importlib.import_module("kicad_mcp.tools.routing_autorouter")
    server = FastMCP("routing-autorouter-registration")
    service = FakeService()

    adapter.register(server, adapter.RoutingAutorouterDependencies(service=service))

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["route_autoroute_freerouting"]
    tool = tools[0]
    assert str(inspect.signature(tool.fn)) == (
        "(dsn_path: 'str' = 'output/routing/board.dsn', "
        "ses_path: 'str' = 'output/routing/board.ses', "
        "net_classes_to_ignore: 'list[str] | None' = None, "
        "exclude_nets: 'list[str] | None' = None, max_passes: 'int' = 100, "
        "thread_count: 'int' = 4, use_docker: 'bool' = True, "
        "freerouting_jar_path: 'str | None' = None, "
        "drc_report_path: 'str' = 'output/routing/freerouting.drc.json', "
        "ctx: 'Context[Any, Any] | None' = None) -> 'ToolResult'"
    )
    assert "Run FreeRouting after placement" in (tool.fn.__doc__ or "")
    metadata = get_tool_metadata("route_autoroute_freerouting")
    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False
    assert metadata.dependencies == ("freerouting",)

    ctx = FakeContext()
    result = await tool.fn(
        dsn_path="custom/in.dsn",
        ses_path="custom/out.ses",
        max_passes=12,
        thread_count=6,
        ctx=ctx,
    )

    assert result.tool_name == "route_autoroute_freerouting"
    assert ctx.progress == [(10, 100, "test")]
    call = service.calls[0]
    assert call["dsn_path"] == "custom/in.dsn"
    assert call["ses_path"] == "custom/out.ses"
    assert call["max_passes"] == 12
    assert call["thread_count"] == 6


@pytest.mark.anyio
async def test_progress_bridge_preserves_value_error_suppression() -> None:
    adapter = importlib.import_module("kicad_mcp.tools.routing_autorouter")

    class RejectingContext:
        async def report_progress(
            self,
            progress: float,
            total: float,
            message: str,
        ) -> None:
            raise ValueError("progress unavailable")

    await adapter._report_progress(
        RejectingContext(),
        10,
        100,
        "ignored",
    )
