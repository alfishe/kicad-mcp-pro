"""Thin FastMCP adapter for JLCPCB CPL rotation correction."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer as FastMCP

from ..config import get_config
from ..manufacturing.cpl_rotation import ManufacturingCplRotationService
from .metadata import headless_compatible


@dataclass(frozen=True)
class ManufacturingCplRotationDependencies:
    service: ManufacturingCplRotationService


def _default_dependencies() -> ManufacturingCplRotationDependencies:
    return ManufacturingCplRotationDependencies(
        service=ManufacturingCplRotationService(
            resolve_path=lambda path: get_config().resolve_within_project(path),
        )
    )


def register(
    mcp: FastMCP,
    dependencies: ManufacturingCplRotationDependencies | None = None,
) -> None:
    """Register the JLCPCB CPL rotation correction tool."""
    deps = dependencies or _default_dependencies()

    @mcp.tool()
    @headless_compatible
    def mfg_correct_cpl_rotations(
        cpl_csv_path: str,
        output_path: str = "",
        dry_run: bool = True,
        confirm: bool = False,
    ) -> str:
        """Apply JLCPCB CPL rotation corrections to a KiCad-exported pick-and-place CSV.

        KiCad exports component orientations relative to its own coordinate system,
        which differs from what JLCPCB's SMT assembly service expects.  This tool
        reads a CPL CSV (produced by export_pos), applies per-footprint rotation
        offsets from the bundled ``jlcpcb_rotations.json`` table, and writes a
        corrected CSV ready for direct upload to JLCPCB.

        Columns expected (KiCad default CPL export):
            Ref, Val, Package, PosX, PosY, Rot, Side

        Args:
            cpl_csv_path: Path to the CPL CSV file (relative to project dir).
            output_path: Output path for the corrected CSV.  Defaults to
                ``<stem>_jlcpcb_corrected.csv`` next to the input file.
            dry_run: If True, return a preview table without writing the file.
            confirm: Must be True when ``dry_run`` is False and a file will be written.

        Returns:
            Summary of corrections applied, or a preview table for dry_run.
        """
        return deps.service.correct(
            cpl_csv_path,
            output_path=output_path,
            dry_run=dry_run,
            confirm=confirm,
        )
