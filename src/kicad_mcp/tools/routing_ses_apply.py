"""Thin FastMCP adapter for headless Specctra SES apply."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer as FastMCP

from ..config import get_config
from ..models.tool_result import ToolResult
from ..routing.ses_apply import RoutingSesApplyService
from ..routing.specctra_staging import relative_project_path
from .metadata import headless_compatible
from .pcb import _transactional_board_write


@dataclass(frozen=True)
class RoutingSesApplyDependencies:
    service: RoutingSesApplyService


def _default_dependencies() -> RoutingSesApplyDependencies:
    return RoutingSesApplyDependencies(
        service=RoutingSesApplyService(
            resolve_within_project=lambda path: get_config().resolve_within_project(path),
            relative_project_path=lambda path: relative_project_path(
                path,
                get_config().project_root,
            ),
            transactional_board_write=_transactional_board_write,
        )
    )


def register(
    mcp: FastMCP,
    dependencies: RoutingSesApplyDependencies | None = None,
) -> None:
    """Register headless Specctra SES apply."""
    deps = dependencies or _default_dependencies()

    @mcp.tool()
    @headless_compatible
    def route_apply_ses(ses_path: str = "output/routing/board.ses") -> ToolResult:
        """Apply a routed Specctra SES to the active board headlessly -- no GUI step.

        KiCad has no headless SES import, so this parses the routed session and writes its
        segments and vias directly into the .kicad_pcb via the round-trip-safe S-expression
        layer; the rest of the board file is untouched. Re-applying the same session is
        deterministic and idempotent (it replaces, not duplicates, the routing). This closes
        the manual File > Import > Specctra Session step. Run run_drc() afterwards to verify.
        """
        return deps.service.apply(ses_path)
