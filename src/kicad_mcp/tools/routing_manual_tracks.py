"""Thin FastMCP adapter for manual track routing tools."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from mcp.server.mcpserver import MCPServer as FastMCP

from ..connection import get_board
from ..models.common import _PadLike
from ..pcb.board_access import board_pads
from ..pcb.live_edit_runtime import execute_live_board_mutation
from ..routing.manual_tracks import RoutingManualTrackService
from ..utils.layers import resolve_layer
from .metadata import requires_kicad_running


@dataclass(frozen=True)
class RoutingManualTrackDependencies:
    service: RoutingManualTrackService


def _default_dependencies() -> RoutingManualTrackDependencies:
    return RoutingManualTrackDependencies(
        service=RoutingManualTrackService(
            resolve_layer=resolve_layer,
            list_pads=lambda: cast(list[_PadLike], board_pads(get_board())),
            execute_mutation=lambda operation, command: execute_live_board_mutation(
                operation,
                command,
                verifier=None,
            ),
        )
    )


def register(
    mcp: FastMCP,
    dependencies: RoutingManualTrackDependencies | None = None,
) -> None:
    """Register manual track routing tools."""
    deps = dependencies or _default_dependencies()

    @mcp.tool()
    @requires_kicad_running
    def route_single_track(
        x1_mm: float,
        y1_mm: float,
        x2_mm: float,
        y2_mm: float,
        layer: str = "F_Cu",
        width_mm: float = 0.25,
        net_name: str = "",
    ) -> str:
        """Route a single straight track segment."""
        return deps.service.route_single(
            x1_mm,
            y1_mm,
            x2_mm,
            y2_mm,
            layer,
            width_mm,
            net_name,
        )

    @mcp.tool()
    @requires_kicad_running
    def route_from_pad_to_pad(
        ref1: str,
        pad1: str,
        ref2: str,
        pad2: str,
        layer: str = "F_Cu",
        width_mm: float = 0.25,
    ) -> str:
        """Create a simple orthogonal route between two pads."""
        return deps.service.route_pad_to_pad(
            ref1,
            pad1,
            ref2,
            pad2,
            layer,
            width_mm,
        )
