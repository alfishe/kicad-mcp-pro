from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries


def test_architecture_checker_tracks_si_solver_capability_service_and_adapter() -> None:
    assert "kicad_mcp.signal_integrity.solver_capabilities" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.signal_integrity.solver_capabilities" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.signal_integrity_solver_capabilities" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.tools.signal_integrity" in boundaries.DOMAIN_MODULES


def test_si_solver_capability_adapter_stays_thin_and_away_from_root() -> None:
    module_name = "kicad_mcp.tools.signal_integrity_solver_capabilities"
    adapter = boundaries.DOMAIN_MODULES[module_name]
    assert "kicad_mcp.tools.signal_integrity" not in boundaries._imports_for(
        module_name,
        adapter,
    )
    span = boundaries._function_span(adapter, "register")
    assert span is not None
    assert span <= 55
    assert boundaries.REGISTER_LINE_LIMITS[module_name] == 55


def test_si_root_delegates_solver_capabilities_and_shrinks() -> None:
    root = boundaries.DOMAIN_MODULES["kicad_mcp.tools.signal_integrity"]
    tree = ast.parse(root.read_text(encoding="utf-8"), filename=str(root))
    register_node = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register"
    )
    nested = {
        node.name
        for node in register_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "si_get_solver_capabilities" not in nested
    span = boundaries._function_span(root, "register")
    assert span is not None
    assert span <= 690
    assert boundaries.REGISTER_LINE_LIMITS["kicad_mcp.tools.signal_integrity"] <= 690


def test_si_root_drops_solver_capability_only_dependencies() -> None:
    root = boundaries.DOMAIN_MODULES["kicad_mcp.tools.signal_integrity"]
    source = root.read_text(encoding="utf-8")

    assert "import json" not in source
    assert "impedance_method" not in source
    assert "ir_drop_method" not in source
    assert "pdn_mesh_method" not in source
    assert "thermal_method" not in source
    assert "thermal_fd_method" not in source
    assert "emc_method" not in source
    assert "channel_method" in source
