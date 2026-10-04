"""Thin FastMCP adapter for net-class routing-rule tools."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer as FastMCP

from ..routing.net_class_rules import RoutingNetClassRuleService, RuleWriter
from .metadata import headless_compatible


@dataclass(frozen=True)
class RoutingNetClassRuleDependencies:
    service: RoutingNetClassRuleService


def dependencies(write_rule: RuleWriter) -> RoutingNetClassRuleDependencies:
    """Build adapter dependencies from the composition root's rule writer."""
    return RoutingNetClassRuleDependencies(
        service=RoutingNetClassRuleService(write_rule=write_rule)
    )


def register(
    mcp: FastMCP,
    dependencies: RoutingNetClassRuleDependencies,
) -> None:
    """Register net-class routing-rule tools."""
    deps = dependencies

    @mcp.tool()
    @headless_compatible
    def route_set_net_class_rules(
        net_class: str,
        width_mm: float,
        clearance_mm: float,
        via_diameter_mm: float,
        via_drill_mm: float,
    ) -> str:
        """Write net-class routing constraints into the active .kicad_dru file."""
        return deps.service.set_rules(
            net_class,
            width_mm,
            clearance_mm,
            via_diameter_mm,
            via_drill_mm,
        )
