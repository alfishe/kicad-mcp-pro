"""Manufacturing tools: panelization (KiKit), test-plan generation, and release manifest.

Tools in this module complement ``export_manufacturing_package`` with:
- ``mfg_panelize`` — wrap KiKit CLI for grid/mousebites/V-cut panels.
- ``mfg_generate_test_plan`` — generate a bring-up test checklist from design intent.
- ``mfg_generate_release_manifest`` — produce a SHA256-signed release manifest JSON.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from mcp.server.mcpserver import MCPServer as FastMCP

from .. import __version__
from ..config import get_config
from ..discovery import get_cli_capabilities
from ..manufacturing.release_evidence import find_release_files, sha256_file
from .metadata import headless_compatible

logger = structlog.get_logger(__name__)

PanelLayout = Literal["grid", "mousebites", "vcut"]

def _kikit_available() -> bool:
    return shutil.which("kikit") is not None


def register(mcp: FastMCP) -> None:
    """Register manufacturing tools."""

    @mcp.tool()
    @headless_compatible
    def mfg_panelize(
        layout: str = "grid",
        rows: int = 2,
        cols: int = 2,
        spacing_mm: float = 2.0,
        frame_width_mm: float = 5.0,
        output_path: str = "",
        dry_run: bool = True,
        confirm: bool = False,
    ) -> str:
        """Panelize the active PCB using KiKit.

        Creates a panel of multiple boards for efficient PCB fabrication.
        Requires ``kikit`` to be installed (``pip install kikit``).

        Args:
            layout: Panel layout type: ``"grid"`` (rectangular array),
                ``"mousebites"`` (tab+mousebite breakaway), or ``"vcut"`` (V-cut scoring).
            rows: Number of board rows in the panel.
            cols: Number of board columns in the panel.
            spacing_mm: Gap between boards in mm.
            frame_width_mm: Panel frame/rail width in mm.
            output_path: Optional output file path (relative to output_dir).
                Defaults to ``panel/<boardname>_panel_<rows>x<cols>.kicad_pcb``.
            dry_run: If True, return the planned command and output path without writing files.
            confirm: Must be True when ``dry_run`` is False to run KiKit.

        Returns:
            Confirmation with the panel file path, or an error message.
        """
        if not _kikit_available():
            return (
                "KiKit is not installed. "
                "Install it with: pip install kikit\n"
                "KiKit documentation: https://github.com/yaqwsx/KiKit"
            )

        cfg = get_config()
        if cfg.pcb_file is None or not cfg.pcb_file.exists():
            return "No PCB file is configured. Call kicad_set_project() first."

        layout_lower = layout.lower()
        if layout_lower not in ("grid", "mousebites", "vcut"):
            return f"Invalid layout '{layout}'. Choose from: grid, mousebites, vcut."

        if rows < 1 or cols < 1:
            return "rows and cols must both be >= 1."

        out_dir = cfg.ensure_output_dir("panel")

        board_stem = cfg.pcb_file.stem
        if output_path:
            panel_file = cfg.resolve_within_project(output_path)
        else:
            panel_file = out_dir / f"{board_stem}_panel_{rows}x{cols}.kicad_pcb"

        # Build KiKit command
        if layout_lower == "grid":
            cmd = [
                "kikit",
                "panelize",
                "--layout",
                f"grid; rows: {rows}; cols: {cols}; space: {spacing_mm}mm",
                "--tabs",
                "fixed; width: 3mm; count: 1",
                "--cuts",
                "mousebites; drill: 0.5mm; spacing: 0.8mm",
                "--framing",
                f"railstb; width: {frame_width_mm}mm",
                "--post",
                "millRoundedCorner",
                str(cfg.pcb_file),
                str(panel_file),
            ]
        elif layout_lower == "mousebites":
            cmd = [
                "kikit",
                "panelize",
                "--layout",
                f"grid; rows: {rows}; cols: {cols}; space: {spacing_mm}mm",
                "--tabs",
                "fixed; width: 3mm; count: 2",
                "--cuts",
                "mousebites; drill: 0.5mm; spacing: 0.8mm; offset: 0.25mm",
                "--framing",
                f"railstb; width: {frame_width_mm}mm",
                str(cfg.pcb_file),
                str(panel_file),
            ]
        else:  # vcut
            cmd = [
                "kikit",
                "panelize",
                "--layout",
                f"grid; rows: {rows}; cols: {cols}; space: 0mm",
                "--tabs",
                "full",
                "--cuts",
                "vcuts; clearance: 0.5mm",
                "--framing",
                f"railstb; width: {frame_width_mm}mm",
                str(cfg.pcb_file),
                str(panel_file),
            ]

        if dry_run:
            return (
                "Dry run: panelization was not executed.\n"
                f"- Output: {panel_file}\n"
                f"- Layout: {layout_lower} {rows}x{cols}, spacing={spacing_mm}mm, "
                f"frame={frame_width_mm}mm\n"
                f"- Command: {' '.join(cmd)}\n"
                "Set dry_run=false and confirm=true to create the panel file."
            )
        if not confirm:
            return (
                "Panelization requires explicit confirmation because it writes a PCB file.\n"
                f"- Intended output: {panel_file}\n"
                "Rerun with dry_run=false and confirm=true."
            )
        if panel_file.exists():
            return (
                "Refusing to overwrite an existing panel file without choosing a new output_path.\n"
                f"- Existing file: {panel_file}"
            )

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            return "KiKit panelization timed out after 120 seconds."
        except (OSError, FileNotFoundError) as exc:
            return f"Failed to run KiKit: {exc}"

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()[:500]
            return f"KiKit panelization failed (exit {result.returncode}):\n{stderr}"

        return (
            f"Panel created: {panel_file}\n"
            f"Layout: {layout} {rows}x{cols}, spacing={spacing_mm}mm, frame={frame_width_mm}mm\n"
            f"Open the panel file in KiCad to verify before submitting to fabricator."
        )

    from . import manufacturing_test_plan

    manufacturing_test_plan.register(mcp)

    @mcp.tool()
    @headless_compatible
    def mfg_generate_release_manifest(output_path: str = "") -> str:
        """Generate a SHA256-signed release manifest for the manufacturing package.

        Collects all files in the output directory, computes SHA256 hashes, and
        records tool versions, intent hash, and gate status into a ``manifest.json``
        and ``MANIFEST.txt``.

        Args:
            output_path: Subdirectory inside the project (defaults to ``output/``).

        Returns:
            Confirmation with manifest path and file count.
        """
        from .project import load_design_intent

        cfg = get_config()
        out_dir = cfg.output_dir or (cfg.project_dir / "output")  # type: ignore[operator]

        if not out_dir.exists():
            return (
                f"Output directory does not exist: {out_dir}\n"
                "Run export_manufacturing_package() first."
            )

        # Gather all files
        release_files = find_release_files(out_dir)
        if not release_files:
            return (
                "No release files found in output directory.\n"
                "Run export_manufacturing_package() first to generate Gerber/drill/BOM files."
            )

        # Compute per-file hashes, sorted by name for deterministic, reproducible output.
        file_hashes: list[dict[str, str]] = sorted(
            (
                {
                    "filename": f.name,
                    "sha256": sha256_file(f),
                    "size_bytes": str(f.stat().st_size),
                }
                for f in release_files
            ),
            key=lambda entry: entry["filename"],
        )

        # Intent hash
        intent = load_design_intent()
        intent_json = json.dumps(intent.model_dump(), sort_keys=True)
        intent_hash = hashlib.sha256(intent_json.encode()).hexdigest()[:16]

        # Provenance: what produced this package (kept out of the wall-clock path so the
        # content_hash stays stable across runs for identical inputs).
        caps = get_cli_capabilities(cfg.kicad_cli)
        source_hashes = {
            label: sha256_file(path)
            for label, path in (
                ("project", cfg.project_file),
                ("pcb", cfg.pcb_file),
                ("schematic", cfg.sch_file),
            )
            if path is not None and path.exists()
        }
        provenance: dict[str, Any] = {
            "kicad_mcp_version": __version__,
            "kicad_cli": str(cfg.kicad_cli),
            "kicad_cli_version": caps.version,
            "intent_hash": intent_hash,
            "source_hashes": source_hashes,
        }

        # content_hash is a stable fingerprint of the package contents plus what produced
        # them: identical inputs -> identical content_hash, regardless of generation time.
        content_basis = json.dumps({"files": file_hashes, "provenance": provenance}, sort_keys=True)
        content_hash = hashlib.sha256(content_basis.encode()).hexdigest()

        manifest: dict[str, Any] = {
            "kicad_mcp_version": __version__,
            "generated_utc": datetime.now(UTC).isoformat(),
            "content_hash": content_hash,
            "intent_hash": intent_hash,
            "provenance": provenance,
            "files": file_hashes,
        }

        # Write manifest.json
        manifest_json_path = out_dir / "manifest.json"
        manifest_json_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        # Write MANIFEST.txt (human-readable)
        txt_lines = [
            "kicad-mcp-pro Release Manifest",
            f"Generated: {manifest['generated_utc']}",
            f"Tool version: kicad-mcp-pro {__version__}",
            f"KiCad CLI version: {caps.version or 'unknown'}",
            f"Content hash: {content_hash}",
            f"Intent hash: {intent_hash}",
            "",
            f"{'Filename':<50} {'SHA256':>16}",
            "-" * 70,
        ]
        for entry in file_hashes:
            txt_lines.append(f"{entry['filename']:<50} {entry['sha256'][:16]}")

        manifest_txt_path = out_dir / "MANIFEST.txt"
        manifest_txt_path.write_text("\n".join(txt_lines), encoding="utf-8")

        return (
            f"Release manifest generated:\n"
            f"- {manifest_json_path} ({len(file_hashes)} files)\n"
            f"- {manifest_txt_path}\n"
            f"Content hash: {content_hash}\n"
            f"Intent hash: {intent_hash}\n"
            f"Files covered: {', '.join(e['filename'] for e in file_hashes[:10])}"
            + ("…" if len(file_hashes) > 10 else "")
        )

    from . import manufacturing_cpl_rotation

    manufacturing_cpl_rotation.register(mcp)

    from . import manufacturing_imports

    manufacturing_imports.register(mcp)

    from . import manufacturing_release_evidence

    manufacturing_release_evidence.register(mcp)
