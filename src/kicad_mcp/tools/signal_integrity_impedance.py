"""Thin FastMCP adapter for signal-integrity impedance tools."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer as FastMCP

from ..signal_integrity.impedance import SignalIntegrityImpedanceService


@dataclass(frozen=True)
class SignalIntegrityImpedanceDependencies:
    service: SignalIntegrityImpedanceService


def _default_dependencies() -> SignalIntegrityImpedanceDependencies:
    return SignalIntegrityImpedanceDependencies(service=SignalIntegrityImpedanceService())


def register(
    mcp: FastMCP,
    dependencies: SignalIntegrityImpedanceDependencies | None = None,
) -> None:
    """Register signal-integrity impedance tools."""
    deps = dependencies or _default_dependencies()

    @mcp.tool()
    def si_calculate_trace_impedance(
        width_mm: float,
        height_mm: float,
        er: float = 4.2,
        trace_type: str = "microstrip",
        copper_oz: float = 1.0,
        spacing_mm: float = 0.2,
    ) -> str:
        """Estimate PCB trace impedance using quasi-static interconnect formulas."""
        return deps.service.calculate_trace_impedance(
            width_mm,
            height_mm,
            er,
            trace_type,
            copper_oz,
            spacing_mm,
        )

    @mcp.tool()
    def si_calculate_trace_width_for_impedance(
        target_ohm: float,
        height_mm: float,
        er: float = 4.2,
        trace_type: str = "microstrip",
        copper_oz: float = 1.0,
        spacing_mm: float = 0.2,
    ) -> str:
        """Solve for a trace width that meets the requested impedance target."""
        return deps.service.calculate_trace_width_for_impedance(
            target_ohm,
            height_mm,
            er,
            trace_type,
            copper_oz,
            spacing_mm,
        )
