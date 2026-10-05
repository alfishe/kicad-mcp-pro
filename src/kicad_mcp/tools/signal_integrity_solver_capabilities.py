"""Thin FastMCP adapter for signal-integrity solver capability tools."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer as FastMCP

from ..signal_integrity.solver_capabilities import (
    SignalIntegritySolverCapabilitiesService,
)


@dataclass(frozen=True)
class SignalIntegritySolverCapabilitiesDependencies:
    service: SignalIntegritySolverCapabilitiesService


def _default_dependencies() -> SignalIntegritySolverCapabilitiesDependencies:
    return SignalIntegritySolverCapabilitiesDependencies(
        service=SignalIntegritySolverCapabilitiesService()
    )


def register(
    mcp: FastMCP,
    dependencies: SignalIntegritySolverCapabilitiesDependencies | None = None,
) -> None:
    """Register signal-integrity solver capability tools."""
    deps = dependencies or _default_dependencies()

    @mcp.tool()
    def si_get_solver_capabilities() -> str:
        """Report configured solver-grade analysis capabilities and unavailable seams."""
        return deps.service.report()
