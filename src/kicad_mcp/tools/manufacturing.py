"""Manufacturing tools: panelization (KiKit), test-plan generation, and release manifest.

Tools in this module complement ``export_manufacturing_package`` with:
- ``mfg_panelize`` — wrap KiKit CLI for grid/mousebites/V-cut panels.
- ``mfg_generate_test_plan`` — generate a bring-up test checklist from design intent.
- ``mfg_generate_release_manifest`` — produce a SHA256-signed release manifest JSON.
"""

from __future__ import annotations

from typing import Literal

import structlog
from mcp.server.mcpserver import MCPServer as FastMCP


logger = structlog.get_logger(__name__)

PanelLayout = Literal["grid", "mousebites", "vcut"]


def register(mcp: FastMCP) -> None:
    """Register manufacturing tools."""

    from . import manufacturing_panelization

    manufacturing_panelization.register(mcp)

    from . import manufacturing_test_plan

    manufacturing_test_plan.register(mcp)

    from . import manufacturing_release_manifest

    manufacturing_release_manifest.register(mcp)

    from . import manufacturing_cpl_rotation

    manufacturing_cpl_rotation.register(mcp)

    from . import manufacturing_imports

    manufacturing_imports.register(mcp)

    from . import manufacturing_release_evidence

    manufacturing_release_evidence.register(mcp)
