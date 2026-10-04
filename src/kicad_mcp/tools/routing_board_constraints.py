"""Thin FastMCP adapter for design-intent board constraints."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer as FastMCP

from ..models.tool_result import ToolResult
from ..routing.board_constraints import (
    DesignIntentLoader,
    RoutingBoardConstraintsService,
    RuleWriter,
)
from .metadata import headless_compatible


@dataclass(frozen=True)
class RoutingBoardConstraintsDependencies:
    service: RoutingBoardConstraintsService


def dependencies(
    *,
    load_design_intent: DesignIntentLoader,
    write_rule: RuleWriter,
) -> RoutingBoardConstraintsDependencies:
    return RoutingBoardConstraintsDependencies(
        service=RoutingBoardConstraintsService(
            load_design_intent=load_design_intent,
            write_rule=write_rule,
        )
    )


def register(
    mcp: FastMCP,
    dependencies: RoutingBoardConstraintsDependencies,
) -> None:
    """Register design-intent board-constraint tools."""
    deps = dependencies

    @mcp.tool()
    @headless_compatible
    def generate_board_constraints() -> ToolResult:
        """Generate .kicad_dru rules and net-class constraints from the project design intent.

        Reads power_rails and interfaces from the stored design intent
        (project_get_design_spec / import_design_spec) and synthesises:
        - Minimum trace widths from IPC-2221 current-capacity formula (power rails)
        - Net-class clearance + width + via rules (per-rail)
        - Differential-pair skew / length / impedance rules (per interface)
        - HV creepage/clearance rules for rails above 50 V

        Run drc_check_rule_conflicts() afterwards to surface any conflicts.
        """
        return deps.service.generate()
