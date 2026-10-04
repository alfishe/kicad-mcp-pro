from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries


def test_architecture_checker_tracks_routing_differential_pair_service_and_adapter() -> None:
    assert "kicad_mcp.routing.differential_pair_rules" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.routing.differential_pair_rules" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.routing_differential_pair" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.tools.routing" in boundaries.DOMAIN_MODULES


def test_routing_differential_pair_adapter_stays_thin_and_away_from_root() -> None:
    module_name = "kicad_mcp.tools.routing_differential_pair"
    adapter = boundaries.DOMAIN_MODULES[module_name]
    assert "kicad_mcp.tools.routing" not in boundaries._imports_for(module_name, adapter)
    span = boundaries._function_span(adapter, "register")
    assert span is not None
    assert span <= 80
    assert boundaries.REGISTER_LINE_LIMITS[module_name] == 80


def test_routing_root_delegates_differential_pair_and_shrinks() -> None:
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
    assert "route_differential_pair" not in nested
    span = boundaries._function_span(root, "register")
    assert span is not None
    assert span <= 740
    assert boundaries.REGISTER_LINE_LIMITS["kicad_mcp.tools.routing"] <= 740


def test_routing_root_drops_differential_pair_helpers_and_uses_late_bound_callbacks() -> None:
    root = boundaries.DOMAIN_MODULES["kicad_mcp.tools.routing"]
    source = root.read_text(encoding="utf-8")
    assert "def _infer_diff_pair_base(" not in source
    assert "def _diff_pair_rule_body(" not in source
    assert "list_board_net_names=lambda: _list_board_net_names()" in source
    assert "write_rule=lambda name, body: _write_rule(name, body)" in source
