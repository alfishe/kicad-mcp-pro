from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries


def test_architecture_checker_tracks_time_domain_service_and_adapter() -> None:
    assert "kicad_mcp.routing.time_domain_tuning" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.routing.time_domain_tuning" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.routing_time_domain_tuning" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.tools.routing" in boundaries.DOMAIN_MODULES


def test_time_domain_adapter_stays_thin_and_away_from_root() -> None:
    module_name = "kicad_mcp.tools.routing_time_domain_tuning"
    adapter = boundaries.DOMAIN_MODULES[module_name]
    assert "kicad_mcp.tools.routing" not in boundaries._imports_for(module_name, adapter)
    span = boundaries._function_span(adapter, "register")
    assert span is not None
    assert span <= 65
    assert boundaries.REGISTER_LINE_LIMITS[module_name] == 65


def test_routing_root_delegates_time_domain_tuning_and_shrinks() -> None:
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

    assert "route_tune_time_domain" not in nested
    span = boundaries._function_span(root, "register")
    assert span is not None
    assert span <= 480
    assert boundaries.REGISTER_LINE_LIMITS["kicad_mcp.tools.routing"] <= 480


def test_routing_root_preserves_time_domain_registration_order() -> None:
    root = boundaries.DOMAIN_MODULES["kicad_mcp.tools.routing"]
    source = root.read_text(encoding="utf-8")

    profiles = source.index("routing_tuning_profiles.register(mcp)")
    time_domain = source.index("routing_time_domain_tuning.register(")
    pair = source.index("routing_diff_pair_length.register(")
    constraints = source.index("routing_board_constraints.register(")
    assert profiles < time_domain < pair < constraints
