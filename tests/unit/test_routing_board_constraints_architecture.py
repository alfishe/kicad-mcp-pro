from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries


def test_architecture_checker_tracks_routing_board_constraints_service_and_adapter() -> None:
    assert "kicad_mcp.routing.board_constraints" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.routing.board_constraints" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.routing_board_constraints" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.tools.routing" in boundaries.DOMAIN_MODULES


def test_routing_board_constraints_adapter_stays_thin_and_away_from_root() -> None:
    module_name = "kicad_mcp.tools.routing_board_constraints"
    adapter = boundaries.DOMAIN_MODULES[module_name]
    assert "kicad_mcp.tools.routing" not in boundaries._imports_for(module_name, adapter)
    span = boundaries._function_span(adapter, "register")
    assert span is not None
    assert span <= 65
    assert boundaries.REGISTER_LINE_LIMITS[module_name] == 65


def test_routing_root_delegates_board_constraints_and_shrinks() -> None:
    root = boundaries.DOMAIN_MODULES["kicad_mcp.tools.routing"]
    tree = ast.parse(root.read_text(encoding="utf-8"), filename=str(root))
    register_node = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register"
    )
    nested = {
        node.name
        for node in register_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "generate_board_constraints" not in nested
    span = boundaries._function_span(root, "register")
    assert span is not None
    assert span <= 570
    assert boundaries.REGISTER_LINE_LIMITS["kicad_mcp.tools.routing"] <= 570


def test_routing_root_preserves_late_bound_callbacks_and_final_registration_order() -> None:
    root = boundaries.DOMAIN_MODULES["kicad_mcp.tools.routing"]
    source = root.read_text(encoding="utf-8")

    assert "def _ipc_width_mm(" not in source
    assert "load_design_intent=lambda: _load_design_intent()" in source
    assert "write_rule=lambda name, body: _write_rule(name, body)" in source
    pair = source.index("routing_diff_pair_length.register(")
    constraints = source.index("routing_board_constraints.register(")
    assert pair < constraints
