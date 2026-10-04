"""Thin FastMCP adapter for differential-pair length tuning."""

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
class RoutingDiffPairLengthDependencies:
    service: RoutingLengthTuningService


def dependencies(
    *,
    list_board_net_names: NetNamesProvider,
    current_track_length_mm: TrackLengthProvider,
    write_rule: RuleWriter,
) -> RoutingDiffPairLengthDependencies:
    return RoutingDiffPairLengthDependencies(
        service=RoutingLengthTuningService(
            list_board_net_names=list_board_net_names,
            current_track_length_mm=current_track_length_mm,
            write_rule=write_rule,
        )
    )


def register(
    mcp: FastMCP,
    dependencies: RoutingDiffPairLengthDependencies,
) -> None:
    """Register differential-pair length-tuning tools."""
    deps = dependencies

    @mcp.tool()
    @headless_compatible
    def tune_diff_pair_length(
        net_name_p: str,
        net_name_n: str,
        target_length_mm: float,
    ) -> str:
        """Write matched-length rules for both nets in a differential pair."""
        return deps.service.tune_diff_pair(net_name_p, net_name_n, target_length_mm)
