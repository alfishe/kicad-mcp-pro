from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries


def test_architecture_checker_tracks_routing_autorouter_service_and_adapter() -> None:
    assert "kicad_mcp.routing.autorouter" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.routing.autorouter" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.routing_autorouter" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.tools.routing" in boundaries.DOMAIN_MODULES


def test_routing_autorouter_adapter_stays_thin_and_away_from_root() -> None:
    module_name = "kicad_mcp.tools.routing_autorouter"
    adapter = boundaries.DOMAIN_MODULES[module_name]
    assert "kicad_mcp.tools.routing" not in boundaries._imports_for(module_name, adapter)
    span = boundaries._function_span(adapter, "register")
    assert span is not None
    assert span <= 105
    assert boundaries.REGISTER_LINE_LIMITS[module_name] == 105


def test_routing_root_has_no_nested_tool_implementations() -> None:
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

    assert nested == set()
    span = boundaries._function_span(root, "register")
    assert span is not None
    assert span <= 100
    assert boundaries.REGISTER_LINE_LIMITS["kicad_mcp.tools.routing"] <= 100


def test_routing_root_drops_autorouter_transport_and_execution_imports() -> None:
    root = boundaries.DOMAIN_MODULES["kicad_mcp.tools.routing"]
    source = root.read_text(encoding="utf-8")

    assert "Context" not in source
    assert "FreeRoutingRunner" not in source
    assert "ManualStepRequiredError" not in source
    assert "apply_ses_to_pcb" not in source
    assert "def _report_progress(" not in source
