"""Thin FastMCP adapter for routing tuning-profile state tools."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer as FastMCP

from ..config import get_config
from ..routing.tuning_profiles import RoutingTuningProfileService
from ..utils.layers import resolve_layer
from .metadata import headless_compatible


@dataclass(frozen=True)
class RoutingTuningProfileDependencies:
    service: RoutingTuningProfileService


def _default_dependencies() -> RoutingTuningProfileDependencies:
    return RoutingTuningProfileDependencies(
        service=RoutingTuningProfileService(
            get_project_dir=lambda: get_config().project_dir,
            resolve_layer=resolve_layer,
        )
    )


def register(
    mcp: FastMCP,
    dependencies: RoutingTuningProfileDependencies | None = None,
) -> None:
    """Register routing tuning-profile tools."""
    deps = dependencies or _default_dependencies()

    @mcp.tool()
    @headless_compatible
    def route_create_tuning_profile(
        name: str,
        layer: str,
        trace_impedance_ohm: float,
        propagation_speed_factor: float,
    ) -> str:
        """Create or update a KiCad 10-style time-domain tuning profile."""
        return deps.service.create(
            name,
            layer,
            trace_impedance_ohm,
            propagation_speed_factor,
        )

    @mcp.tool()
    @headless_compatible
    def route_list_tuning_profiles() -> str:
        """List configured time-domain tuning profiles."""
        return deps.service.list_profiles()

    @mcp.tool()
    @headless_compatible
    def route_apply_tuning_profile(net_pattern: str, profile_name: str) -> str:
        """Assign a named tuning profile to a net or wildcard net group."""
        return deps.service.apply(net_pattern, profile_name)
