from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries


def test_architecture_checker_tracks_manual_track_service_and_adapter() -> None:
    assert "kicad_mcp.routing.manual_tracks" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.routing.manual_tracks" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.routing_manual_tracks" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.tools.routing" in boundaries.DOMAIN_MODULES


def test_manual_track_adapter_stays_thin_and_away_from_root() -> None:
    module_name = "kicad_mcp.tools.routing_manual_tracks"
    adapter = boundaries.DOMAIN_MODULES[module_name]
    assert "kicad_mcp.tools.routing" not in boundaries._imports_for(module_name, adapter)
    span = boundaries._function_span(adapter, "register")
    assert span is not None
    assert span <= 120
    assert boundaries.REGISTER_LINE_LIMITS[module_name] == 120


def test_routing_root_delegates_manual_tracks_and_shrinks() -> None:
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

    assert "route_single_track" not in nested
    assert "route_from_pad_to_pad" not in nested
    span = boundaries._function_span(root, "register")
    assert span is not None
    assert span <= 390
    assert boundaries.REGISTER_LINE_LIMITS["kicad_mcp.tools.routing"] <= 390


def test_routing_root_preserves_manual_track_registration_order() -> None:
    root = boundaries.DOMAIN_MODULES["kicad_mcp.tools.routing"]
    source = root.read_text(encoding="utf-8")

    manual = source.index("routing_manual_tracks.register(mcp)")
    specctra = source.index("routing_specctra_staging.register(mcp)")
    apply_ses = source.index("def route_apply_ses(")
    assert manual < specctra < apply_ses


def test_routing_root_drops_manual_track_specific_helpers_and_imports() -> None:
    root = boundaries.DOMAIN_MODULES["kicad_mcp.tools.routing"]
    source = root.read_text(encoding="utf-8")

    assert "def _find_pad(" not in source
    assert "AddTrackInput" not in source
    assert "Vector2" not in source
    assert "execute_live_board_mutation" not in source
