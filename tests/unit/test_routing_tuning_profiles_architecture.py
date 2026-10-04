from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries


def test_architecture_checker_tracks_routing_tuning_profile_service_and_adapter() -> None:
    assert "kicad_mcp.routing.tuning_profiles" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.routing.tuning_profiles" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.routing_tuning_profiles" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.tools.routing" in boundaries.DOMAIN_MODULES


def test_routing_tuning_profile_adapter_stays_thin_and_away_from_root() -> None:
    module_name = "kicad_mcp.tools.routing_tuning_profiles"
    adapter = boundaries.DOMAIN_MODULES[module_name]
    assert "kicad_mcp.tools.routing" not in boundaries._imports_for(module_name, adapter)
    span = boundaries._function_span(adapter, "register")
    assert span is not None
    assert span <= 95
    assert boundaries.REGISTER_LINE_LIMITS[module_name] == 95


def test_routing_root_delegates_tuning_profile_crud_and_shrinks() -> None:
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

    assert "route_create_tuning_profile" not in nested
    assert "route_list_tuning_profiles" not in nested
    assert "route_apply_tuning_profile" not in nested
    span = boundaries._function_span(root, "register")
    assert span is not None
    assert span <= 850
    assert boundaries.REGISTER_LINE_LIMITS["kicad_mcp.tools.routing"] <= 850


def test_routing_root_uses_canonical_tuning_profile_reader() -> None:
    root = boundaries.DOMAIN_MODULES["kicad_mcp.tools.routing"]
    source = root.read_text(encoding="utf-8")

    assert "load_tuning_profiles(get_config().project_dir)" in source
    assert "def _load_state_file(" not in source
    assert "def _save_state_file(" not in source
