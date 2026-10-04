"""Thin FastMCP adapter for differential-pair routing rules."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer as FastMCP

from ..routing.differential_pair_rules import (
    NetNamesProvider,
    RoutingDifferentialPairService,
    RuleWriter,
)
from .metadata import headless_compatible


@dataclass(frozen=True)
class RoutingDifferentialPairDependencies:
    service: RoutingDifferentialPairService


def dependencies(
    *,
    list_board_net_names: NetNamesProvider,
    write_rule: RuleWriter,
) -> RoutingDifferentialPairDependencies:
    """Build adapter dependencies from late-bound Routing root callbacks."""
    return RoutingDifferentialPairDependencies(
        service=RoutingDifferentialPairService(
            list_board_net_names=list_board_net_names,
            write_rule=write_rule,
        )
    )


def register(
    mcp: FastMCP,
    dependencies: RoutingDifferentialPairDependencies,
) -> None:
    """Register differential-pair routing-rule tools."""
    deps = dependencies

    @mcp.tool()
    @headless_compatible
    def route_differential_pair(
        net_p: str,
        net_n: str,
        layer: str = "F_Cu",
        width_mm: float = 0.2,
        gap_mm: float = 0.2,
        length_tolerance_mm: float = 0.1,
    ) -> str:
        """Write differential-pair routing constraints for a pair of nets."""
        return deps.service.set_pair(
            net_p, net_n, layer, width_mm, gap_mm, length_tolerance_mm
        )
