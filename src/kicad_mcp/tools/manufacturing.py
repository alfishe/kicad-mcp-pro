"""Manufacturing tools: panelization (KiKit), test-plan generation, and release manifest.

Tools in this module complement ``export_manufacturing_package`` with:
- ``mfg_panelize`` — wrap KiKit CLI for grid/mousebites/V-cut panels.
- ``mfg_generate_test_plan`` — generate a bring-up test checklist from design intent.
- ``mfg_generate_release_manifest`` — produce a SHA256-signed release manifest JSON.
"""

from __future__ import annotations

import hashlib
import json
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


def register(mcp: FastMCP) -> None:
    """Register manufacturing tools."""

    from . import manufacturing_panelization

    manufacturing_panelization.register(mcp)

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
