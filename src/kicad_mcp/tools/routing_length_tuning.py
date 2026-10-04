"""Thin FastMCP adapter for single-net length tuning."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer as FastMCP

from ..routing.length_tuning import (
    NetNamesProvider,
    RoutingLengthTuningService,
    RuleWriter,
    TrackLengthProvider,
)
from .metadata import headless_compatible


@dataclass(frozen=True)
class RoutingLengthTuningDependencies:
    service: RoutingLengthTuningService


def dependencies(
    *,
    list_board_net_names: NetNamesProvider,
    current_track_length_mm: TrackLengthProvider,
    write_rule: RuleWriter,
) -> RoutingLengthTuningDependencies:
    return RoutingLengthTuningDependencies(
        service=RoutingLengthTuningService(
            list_board_net_names=list_board_net_names,
            current_track_length_mm=current_track_length_mm,
            write_rule=write_rule,
        )
    )


def register(
    mcp: FastMCP,
    dependencies: RoutingLengthTuningDependencies,
) -> None:
    """Register single-net length-tuning tools."""
    deps = dependencies

    @mcp.tool()
    @headless_compatible
    def route_tune_length(
        net_name: str,
        target_mm: float,
        meander_amplitude_mm: float = 0.5,
        tolerance_mm: float = 0.1,
    ) -> str:
        """Write a length-tuning rule and report the current delta for a net."""
        return deps.service.tune_net(
            net_name,
            target_mm,
            meander_amplitude_mm,
            tolerance_mm,
        )
