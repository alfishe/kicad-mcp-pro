"""Thin FastMCP adapter for Specctra DSN/SES staging tools."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer as FastMCP

from ..config import get_config
from ..models.tool_result import ToolResult
from ..routing.specctra_staging import RoutingSpecctraStagingService
from ..utils.freerouting import FreeRoutingRunner
from .export_support import _get_pcb_file
from .metadata import headless_compatible


@dataclass(frozen=True)
class RoutingSpecctraStagingDependencies:
    service: RoutingSpecctraStagingService


def _default_dependencies() -> RoutingSpecctraStagingDependencies:
    return RoutingSpecctraStagingDependencies(
        service=RoutingSpecctraStagingService(
            runner_factory=FreeRoutingRunner,
            get_pcb_file=_get_pcb_file,
            resolve_within_project=lambda path: get_config().resolve_within_project(path),
            get_project_root=lambda: get_config().project_root,
        )
    )


def register(
    mcp: FastMCP,
    dependencies: RoutingSpecctraStagingDependencies | None = None,
) -> None:
    """Register Specctra DSN/SES staging tools."""
    deps = dependencies or _default_dependencies()

    @mcp.tool()
    @headless_compatible
    def route_export_dsn(output_path: str = "output/routing/board.dsn") -> ToolResult:
        """Export a Specctra DSN for FreeRouting; may require a one-time KiCad GUI step.

        Uses headless ``kicad-cli pcb export specctra`` when the CLI supports it. If KiCad
        cannot export the DSN headlessly, returns a human-gated result describing the
        File > Export > Specctra DSN step instead of failing opaquely.
        """
        return deps.service.export_dsn(output_path)

    @mcp.tool()
    @headless_compatible
    def route_import_ses(ses_path: str = "output/routing/board.ses") -> ToolResult:
        """Stage a routed Specctra SES and surface the required KiCad GUI import step.

        KiCad has no headless SES import, so this stages the session and returns a
        human-gated result: the routing is applied by running File > Import > Specctra
        Session in the PCB Editor. It never reports the board as routed when it is not
        (``changed=False``, ``human_gate_required=True``).
        """
        return deps.service.import_ses(ses_path)
