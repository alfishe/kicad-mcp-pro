"""Thin FastMCP adapter for dielectric-material catalog tools."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer as FastMCP

from ..signal_integrity.dielectric_materials import (
    SignalIntegrityDielectricMaterialsService,
)


@dataclass(frozen=True)
class SignalIntegrityDielectricMaterialsDependencies:
    service: SignalIntegrityDielectricMaterialsService


def _default_dependencies() -> SignalIntegrityDielectricMaterialsDependencies:
    return SignalIntegrityDielectricMaterialsDependencies(
        service=SignalIntegrityDielectricMaterialsService()
    )


def register(
    mcp: FastMCP,
    dependencies: SignalIntegrityDielectricMaterialsDependencies | None = None,
) -> None:
    """Register dielectric-material catalog tools."""
    deps = dependencies or _default_dependencies()

    @mcp.tool()
    def si_list_dielectric_materials() -> str:
        """List all built-in dielectric materials with Er, loss tangent, and frequency range.

        Use the returned material keys with si_synthesize_stackup_for_interfaces()
        to select the appropriate laminate for your design.
        """
        return deps.service.list_materials()
