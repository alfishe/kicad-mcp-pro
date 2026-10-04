from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries


def test_architecture_checker_tracks_routing_net_class_service_and_adapter() -> None:
    assert "kicad_mcp.routing.net_class_rules" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.routing.net_class_rules" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.routing_net_class_rules" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.tools.routing" in boundaries.DOMAIN_MODULES


def test_routing_net_class_adapter_stays_thin_and_away_from_root() -> None:
    module_name = "kicad_mcp.tools.routing_net_class_rules"
    adapter = boundaries.DOMAIN_MODULES[module_name]
    assert "kicad_mcp.tools.routing" not in boundaries._imports_for(module_name, adapter)
    span = boundaries._function_span(adapter, "register")
    assert span is not None
    assert span <= 75
    assert boundaries.REGISTER_LINE_LIMITS[module_name] == 75


def test_routing_root_delegates_net_class_rule_and_shrinks() -> None:
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

    assert "route_set_net_class_rules" not in nested
    span = boundaries._function_span(root, "register")
    assert span is not None
    assert span <= 770
    assert boundaries.REGISTER_LINE_LIMITS["kicad_mcp.tools.routing"] <= 770


def test_routing_root_drops_net_class_builder_and_injects_rule_writer() -> None:
    root = boundaries.DOMAIN_MODULES["kicad_mcp.tools.routing"]
    source = root.read_text(encoding="utf-8")

    assert "def _net_class_rule_body(" not in source
    assert "routing_net_class_rules.dependencies(_write_rule)" in source
