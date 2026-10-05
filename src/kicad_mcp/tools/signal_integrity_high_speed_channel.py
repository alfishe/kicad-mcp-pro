"""Thin FastMCP adapter for high-speed channel analysis."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer as FastMCP

from ..signal_integrity.high_speed_channel import SignalIntegrityHighSpeedChannelService


@dataclass(frozen=True)
class SignalIntegrityHighSpeedChannelDependencies:
    service: SignalIntegrityHighSpeedChannelService


def _default_dependencies() -> SignalIntegrityHighSpeedChannelDependencies:
    return SignalIntegrityHighSpeedChannelDependencies(
        service=SignalIntegrityHighSpeedChannelService()
    )


def register(
    mcp: FastMCP,
    dependencies: SignalIntegrityHighSpeedChannelDependencies | None = None,
) -> None:
    """Register high-speed channel analysis tools."""
    deps = dependencies or _default_dependencies()

    @mcp.tool()
    def si_analyze_high_speed_channel(
        length_mm: float,
        data_rate_gbps: float,
        z0_ohm: float = 50.0,
        eps_eff: float = 3.8,
        loss_tangent: float = 0.02,
        trace_width_mm: float = 0.2,
        amplitude_v: float = 1.0,
        max_insertion_loss_db: float = 10.0,
    ) -> str:
        """Estimate high-speed channel insertion loss and eye opening for a lossy trace.

        Sums conductor skin-effect and dielectric (tan-delta) loss to get insertion loss
        at the Nyquist rate, then a first-order loss-limited eye height, with a
        PASS/WARN/FAIL verdict against ``max_insertion_loss_db``. When an ngspice CLI is
        available the insertion loss is measured from an RLGC-ladder AC sweep; otherwise a
        closed-form estimate is used. The method label states which path produced the
        numbers.
        """
        return deps.service.analyze(
            length_mm=length_mm,
            data_rate_gbps=data_rate_gbps,
            z0_ohm=z0_ohm,
            eps_eff=eps_eff,
            loss_tangent=loss_tangent,
            trace_width_mm=trace_width_mm,
            amplitude_v=amplitude_v,
            max_insertion_loss_db=max_insertion_loss_db,
        )
