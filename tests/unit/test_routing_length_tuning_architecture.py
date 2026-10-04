from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries


def test_architecture_checker_tracks_routing_length_tuning_service_and_adapters() -> None:
    assert "kicad_mcp.routing.length_tuning" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.routing.length_tuning" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.routing_length_tuning" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.tools.routing_diff_pair_length" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.tools.routing" in boundaries.DOMAIN_MODULES


def test_length_tuning_adapters_stay_thin_and_away_from_root() -> None:
    for module_name in (
        "kicad_mcp.tools.routing_length_tuning",
        "kicad_mcp.tools.routing_diff_pair_length",
    ):
        adapter = boundaries.DOMAIN_MODULES[module_name]
        assert "kicad_mcp.tools.routing" not in boundaries._imports_for(module_name, adapter)
        span = boundaries._function_span(adapter, "register")
        assert span is not None
        assert span <= 75
        assert boundaries.REGISTER_LINE_LIMITS[module_name] == 75


def test_routing_root_delegates_length_tuning_and_shrinks() -> None:
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

    assert "route_tune_length" not in nested
    assert "tune_diff_pair_length" not in nested
    span = boundaries._function_span(root, "register")
    assert span is not None
    assert span <= 700
    assert boundaries.REGISTER_LINE_LIMITS["kicad_mcp.tools.routing"] <= 700


def test_routing_root_drops_length_rule_builders_and_preserves_registration_order() -> None:
    root = boundaries.DOMAIN_MODULES["kicad_mcp.tools.routing"]
    source = root.read_text(encoding="utf-8")

    assert "def _length_tune_rule_body(" not in source
    assert "def _diff_pair_length_rule_body(" not in source
    assert "list_board_net_names=lambda: _list_board_net_names()" in source
    assert "current_track_length_mm=lambda net_name: _current_track_length_mm(net_name)" in source
    assert "write_rule=lambda name, body: _write_rule(name, body)" in source

    single = source.index("routing_length_tuning.register(")
    profiles = source.index("routing_tuning_profiles.register(mcp)")
    time_domain = source.index("def route_tune_time_domain(")
    pair = source.index("routing_diff_pair_length.register(")
    constraints = source.index("routing_board_constraints.register(")
    assert single < profiles < time_domain < pair < constraints
